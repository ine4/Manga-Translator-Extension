//! Local-only Rust lifecycle controller. llama.cpp provides the CUDA/GGUF engine.
//! No request bodies, URLs, images, prompts or responses are written to disk.
use axum::{
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap, env, fs, path::{Path, PathBuf},
    process::Stdio, sync::Arc, time::{Duration, Instant},
};
use tokio::{process::{Child, Command}, sync::Mutex, time::sleep};
use uuid::Uuid;
mod engine_options;

#[cfg(windows)]
mod windows_job;

const DEFAULT: &str = include_str!("../default-model.json");
const WORKER: &str = "http://127.0.0.1:7679";
const BROWSER_TTL: Duration = Duration::from_secs(90);
const JOB_TTL: Duration = Duration::from_secs(1800);
type ApiError = (StatusCode, Json<Value>);
type ApiResult = Result<Json<Value>, ApiError>;

fn err(code: StatusCode, msg: &str) -> ApiError {
    (code, Json(json!({"error": {"message":msg}})))
}
fn unavailable(msg: &str) -> ApiError { err(StatusCode::SERVICE_UNAVAILABLE, msg) }

fn authorize(h: &HeaderMap, inference: bool) -> Result<(), ApiError> {
    // No CORS is granted to websites; fail closed for ordinary browser origins.
    if let Some(origin) = h.get("origin") {
        if !origin.to_str().unwrap_or("").starts_with("chrome-extension://") {
            return Err(err(StatusCode::FORBIDDEN, "Local extension only"));
        }
    }
    let control = h.get("x-manga-local").and_then(|v| v.to_str().ok()) == Some("1");
    let internal = inference &&
        h.get("authorization").and_then(|v| v.to_str().ok()) == Some("Bearer manga-local");
    if control || internal { Ok(()) }
    else { Err(err(StatusCode::FORBIDDEN, "Local client header required")) }
}

#[derive(Clone, Deserialize, Serialize, Debug)]
struct Model {
    id: String, label: String, repo: String, revision: String,
    weights: String, projector: String,
}
fn safe_id(v: &str) -> bool {
    !v.is_empty() && v.len() <= 80 &&
        v.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
}
fn safe_file(v: &str) -> bool {
    v.ends_with(".gguf") && !v.starts_with('.') &&
        !v.is_empty() && v.bytes().all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
}
impl Model {
    fn valid(&self) -> bool {
        safe_id(&self.id) && safe_file(&self.weights) && safe_file(&self.projector) &&
            self.weights != self.projector
    }
    fn paths(&self, root: &Path) -> (PathBuf, PathBuf) {
        let dir = root.join(&self.id);
        (dir.join(&self.weights), dir.join(&self.projector))
    }
    fn installed(&self, root: &Path) -> bool {
        let (a, b) = self.paths(root);
        a.is_file() && b.is_file() && self.valid() &&
            [a,b].iter().all(|p| {
                use std::io::Read;
                let mut magic = [0u8;4];
                fs::File::open(p).and_then(|mut f| f.read_exact(&mut magic)).is_ok() && &magic == b"GGUF"
            })
    }
}
fn catalog(root: &Path) -> Vec<Model> {
    let default: Model = serde_json::from_str(DEFAULT).expect("valid default model");
    let mut out = vec![default];
    if let Ok(dirs) = fs::read_dir(root) {
        for dir in dirs.flatten() {
            if !dir.file_type().map(|t| t.is_dir()).unwrap_or(false) { continue; }
            let Ok(raw) = fs::read_to_string(dir.path().join("model.json")) else { continue; };
            let Ok(model) = serde_json::from_str::<Model>(&raw) else { continue; };
            if !model.valid() || dir.file_name().to_str() != Some(model.id.as_str()) { continue; }
            if let Some(i) = out.iter().position(|m| m.id == model.id) { out[i] = model; }
            else { out.push(model); }
        }
    }
    out.sort_by(|a,b| a.id.cmp(&b.id));
    out
}

#[derive(Default)]
struct Leases(HashMap<String, (String, Instant)>);
impl Leases {
    fn prune(&mut self, now: Instant) { self.0.retain(|_, (_, expiry)| *expiry > now); }
    fn allows(&self, model: &str, except: &str) -> bool {
        self.0.iter().all(|(id,(m,_))| id == except || m == model)
    }
    fn set(&mut self, id: String, model: String, expiry: Instant) {
        self.0.insert(id, (model, expiry));
    }
    fn remove(&mut self, id: &str) { self.0.remove(id); }
    fn empty(&self) -> bool { self.0.is_empty() }
}

struct Worker { model: String, key: String, child: Child }
struct Runtime {
    root: PathBuf,
    engine: PathBuf,
    client: reqwest::Client,
    worker: Option<Worker>,
    leases: Leases,
}
impl Runtime {
    async fn stop(&mut self) {
        if let Some(mut w) = self.worker.take() {
            let _ = w.child.kill().await;
            let _ = w.child.wait().await;
        }
    }
    async fn ensure(&mut self, model_id: &str) -> Result<(), ApiError> {
        if let Some(w) = self.worker.as_mut() {
            if w.model == model_id && matches!(w.child.try_wait(), Ok(None)) {
                return Ok(());
            }
        }
        let model = catalog(&self.root).into_iter().find(|m| m.id == model_id)
            .ok_or_else(|| err(StatusCode::NOT_FOUND, "Unknown local model"))?;
        if !model.installed(&self.root) {
            return Err(unavailable("Model not installed. Run setup-local-ai.bat or the model manager."));
        }
        if !self.engine.is_file() {
            return Err(unavailable("CUDA llama-server executable is missing."));
        }
        self.stop().await;
        let (weights, projector) = model.paths(&self.root);
        let key = Uuid::new_v4().to_string();
        let options = engine_options::EngineOptions::load(Path::new("local-ai/engine.json")).map_err(unavailable)?;
        let mut cmd = Command::new(&self.engine);
        cmd.arg("--model").arg(weights).arg("--mmproj").arg(projector)
            .args(["--host","127.0.0.1","--port","7679","--alias",model_id,
                "--device","CUDA0","-ngl","999","--ctx-size","16384","--parallel","1",
                "--api-key",&key,"--no-webui","--log-disable"])
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
            .kill_on_drop(true);
        cmd.args(["--flash-attn", &options.flash_attention])
            .arg("--batch-size").arg(options.batch_size.to_string())
            .arg("--ubatch-size").arg(options.ubatch_size.to_string());
        if let Some(tokens) = options.image_max_tokens {
            cmd.arg("--image-max-tokens").arg(tokens.to_string());
        }
        let mut child = cmd.spawn().map_err(|_| unavailable("Could not start CUDA inference engine"))?;
        let until = Instant::now() + Duration::from_secs(120);
        while Instant::now() < until {
            if !matches!(child.try_wait(), Ok(None)) {
                return Err(unavailable("CUDA inference engine exited during model load"));
            }
            // Wait for actual model readiness, then verify this is our authenticated worker.
            let ready = self.client.get(format!("{WORKER}/health")).bearer_auth(&key).timeout(Duration::from_secs(2))
                .send().await.map(|r| r.status().is_success()).unwrap_or(false);
            if !ready { sleep(Duration::from_millis(250)).await; continue; }
            if let Ok(r) = self.client.get(format!("{WORKER}/v1/models"))
                .bearer_auth(&key).timeout(Duration::from_secs(2)).send().await {
                if r.status().is_success() {
                    self.worker = Some(Worker { model: model_id.to_string(), key, child });
                    return Ok(());
                }
            }
            sleep(Duration::from_millis(250)).await;
        }
        let _ = child.kill().await;
        let _ = child.wait().await;
        Err(unavailable("Local model load timed out"))
    }
    async fn reconcile(&mut self) {
        self.leases.prune(Instant::now());
        if self.leases.empty() { self.stop().await; }
    }
}
type Shared = Arc<Mutex<Runtime>>;

async fn models(State(s): State<Shared>, h: HeaderMap) -> ApiResult {
    authorize(&h, false)?;
    let s = s.lock().await;
    let models: Vec<_> = catalog(&s.root).iter()
        .map(|m| json!({"id":m.id,"label":m.label,"installed":m.installed(&s.root),"repo":m.repo}))
        .collect();
    Ok(Json(json!({"models":models,"loaded_model":s.worker.as_ref().map(|w| &w.model),
        "leases":s.leases.0.len(),"engine_available":s.engine.is_file()})))
}
#[derive(Deserialize)]
struct LeaseRequest { id: String, #[serde(default)] model: String, keep: bool }
async fn lease(State(s): State<Shared>, h: HeaderMap, Json(req): Json<LeaseRequest>) -> ApiResult {
    authorize(&h, false)?;
    let is_job = req.id.starts_with("job:");
    let valid_prefix = is_job || req.id.starts_with("browser:") || req.id.starts_with("gui:");
    let uuid = req.id.split_once(':').and_then(|(_,v)| Uuid::parse_str(v).ok());
    if !valid_prefix || uuid.is_none() || (req.keep && !safe_id(&req.model)) {
        return Err(err(StatusCode::BAD_REQUEST, "Invalid lease"));
    }
    let mut s = s.lock().await;
    s.leases.prune(Instant::now());
    if !req.keep {
        s.leases.remove(&req.id);
        s.reconcile().await;
    } else {
        if !s.leases.allows(&req.model, &req.id) {
            return Err(err(StatusCode::CONFLICT, "Another model has an active session or page"));
        }
        s.ensure(&req.model).await?;
        let ttl = if is_job { JOB_TTL } else { BROWSER_TTL };
        s.leases.set(req.id, req.model, Instant::now() + ttl);
    }
    Ok(Json(json!({"ok":true,"loaded_model":s.worker.as_ref().map(|w| &w.model)})))
}

fn validate_messages(body: &Value) -> bool {
    let Some(messages) = body.get("messages").and_then(Value::as_array) else { return false; };
    !messages.is_empty() && messages.iter().all(|m| {
        if !matches!(m.get("role").and_then(Value::as_str), Some("system" | "user" | "assistant")) {
            return false;
        }
        match m.get("content") {
            Some(Value::String(_)) => true,
            Some(Value::Array(parts)) => parts.iter().all(|p| match p.get("type").and_then(Value::as_str) {
                Some("text") => p.get("text").and_then(Value::as_str).is_some(),
                Some("image_url") => p.pointer("/image_url/url").and_then(Value::as_str)
                    .map(|u| ["data:image/png;base64,","data:image/jpeg;base64,","data:image/webp;base64,"]
                        .iter().any(|prefix| u.starts_with(prefix))).unwrap_or(false),
                _ => false
            }),
            _ => false
        }
    })
}
#[derive(Deserialize)]
struct RemoveRequest { id: String }

async fn remove_model(State(s): State<Shared>, h: HeaderMap, Json(req): Json<RemoveRequest>) -> ApiResult {
    authorize(&h, false)?;
    if !safe_id(&req.id) { return Err(err(StatusCode::BAD_REQUEST, "Invalid model ID")); }
    let mut s = s.lock().await;
    s.reconcile().await;
    if s.worker.as_ref().map(|w| w.model.as_str()) == Some(req.id.as_str()) {
        return Err(err(StatusCode::CONFLICT, "Release the model and wait for active pages to finish first"));
    }
    let dir = s.root.join(&req.id);
    if dir.exists() {
        if !catalog(&s.root).iter().any(|m| m.id == req.id) {
            return Err(err(StatusCode::NOT_FOUND, "Model not registered"));
        }
        fs::remove_dir_all(&dir).map_err(|_| unavailable("Unable to remove model files"))?;
    }
    Ok(Json(json!({"ok":true})))
}

async fn chat(State(s): State<Shared>, h: HeaderMap, Json(body): Json<Value>) -> ApiResult {
    authorize(&h, true)?;
    let model = body.get("model").and_then(Value::as_str)
        .filter(|m| safe_id(m)).ok_or_else(|| err(StatusCode::BAD_REQUEST,"Unknown model"))?;
    if !validate_messages(&body) { return Err(err(StatusCode::BAD_REQUEST, "Only text and inline image data accepted")); }
    let mut s = s.lock().await;
    s.leases.prune(Instant::now());
    if !s.leases.allows(model, "") {
        return Err(err(StatusCode::CONFLICT,"Another model is active"));
    }
    s.ensure(model).await?;
    let worker = s.worker.as_ref().ok_or_else(|| unavailable("Local worker unavailable"))?;
    let mut request = json!({"model":model,"messages":body["messages"],"stream":false,"cache_prompt":false});
    for field in ["temperature","top_p","top_k","max_tokens"] {
        if let Some(v) = body.get(field) { request[field] = v.clone(); }
    }
    // Hold the mutex throughout inference: no reload/unload can interrupt a page chunk.
    // The Python API additionally holds a page lease across all chunks.
    let result = async {
        let response = s.client.post(format!("{WORKER}/v1/chat/completions"))
            .bearer_auth(&worker.key).json(&request).timeout(Duration::from_secs(480))
            .send().await.map_err(|_| unavailable("Local inference connection failed"))?;
        if !response.status().is_success() {
            return Err(unavailable("Local inference rejected the request; check model and context"));
        }
        let data = response.json::<Value>().await.map_err(|_| unavailable("Invalid local inference response"))?;
        Ok(Json(data))
    }.await;
    s.reconcile().await;
    result
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Children inherit this job, so forced controller termination also releases CUDA.
    #[cfg(windows)]
    let _worker_job = windows_job::WorkerJob::new()?;
    let root = PathBuf::from(env::var("MANGA_LOCAL_MODELS").unwrap_or_else(|_| "local-ai/models".into()));
    let engine = PathBuf::from(env::var("MANGA_LLAMA_SERVER").unwrap_or_else(|_| "local-ai/runtime/llama-server.exe".into()));
    let shared = Arc::new(Mutex::new(Runtime { root, engine, worker:None, leases:Leases::default(),
        client:reqwest::Client::builder().no_proxy().build()? }));
    let reaper = Arc::clone(&shared);
    tokio::spawn(async move {
        loop {
            sleep(Duration::from_secs(2)).await;
            reaper.lock().await.reconcile().await;
        }
    });
    let app = Router::new()
        .route("/local/models", get(models))
        .route("/local/lease", post(lease))
        .route("/local/remove", post(remove_model))
        .route("/v1/chat/completions", post(chat))
        .layer(DefaultBodyLimit::max(100 * 1024 * 1024))
        .with_state(Arc::clone(&shared));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:7678").await?;
    println!("Local AI controller ready on 127.0.0.1:7678 (no model loaded)");
    axum::serve(listener, app).with_graceful_shutdown(async { let _ = tokio::signal::ctrl_c().await; }).await?;
    shared.lock().await.stop().await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn expires_and_releases_only_last_lease() {
        let now = Instant::now();
        let mut l = Leases::default();
        l.set("a".into(),"qwen".into(),now + Duration::from_secs(30));
        l.set("b".into(),"qwen".into(),now + Duration::from_secs(60));
        l.prune(now + Duration::from_secs(31));
        assert!(!l.empty());
        assert!(!l.allows("other",""));
        l.remove("b"); assert!(l.empty());
    }
    #[test]
    fn rejects_paths_and_remote_images() {
        assert!(!safe_file("../bad.gguf"));
        assert!(!safe_id("../model"));
        assert!(!validate_messages(&json!({"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"https://example.org/a.png"}}]}]})));
        assert!(validate_messages(&json!({"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,abc"}}]}]})));
    }
    #[test]
    fn official_catalog_valid() {
        let m: Model = serde_json::from_str(DEFAULT).unwrap();
        assert!(m.valid());
    }
    #[test]
    fn rejects_web_origin_even_with_header() {
        let mut headers = HeaderMap::new();
        headers.insert("origin", "https://example.org".parse().unwrap());
        headers.insert("x-manga-local","1".parse().unwrap());
        assert!(authorize(&headers,false).is_err());
    }
}
