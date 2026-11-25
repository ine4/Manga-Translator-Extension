use serde::Deserialize;
use std::{fs, io::ErrorKind, path::Path};

#[derive(Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct EngineOptions {
    pub flash_attention: String,
    pub batch_size: u32,
    pub ubatch_size: u32,
    pub image_max_tokens: Option<u32>,
}

impl Default for EngineOptions {
    fn default() -> Self {
        Self { flash_attention: "auto".into(), batch_size: 2048, ubatch_size: 512, image_max_tokens: None }
    }
}

impl EngineOptions {
    pub fn load(path: &Path) -> Result<Self, &'static str> {
        let options = match fs::read(path) {
            Ok(bytes) => serde_json::from_slice::<Self>(&bytes).map_err(|_| "Invalid engine.json")?,
            Err(error) if error.kind() == ErrorKind::NotFound => Self::default(),
            Err(_) => return Err("Unable to read engine.json"),
        };
        options.validate()?;
        Ok(options)
    }

    fn validate(&self) -> Result<(), &'static str> {
        if !["auto", "on", "off"].contains(&self.flash_attention.as_str())
            || !(128..=8192).contains(&self.batch_size)
            || !(32..=self.batch_size).contains(&self.ubatch_size)
            || self.image_max_tokens.is_some_and(|value| !(256..=8192).contains(&value)) {
            return Err("Engine settings exceed supported bounds");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn defaults_match_the_qualified_engine() { assert!(EngineOptions::default().validate().is_ok()); }
    #[test]
    fn reject_unknown_flags_and_unbounded_allocations() {
        assert!(serde_json::from_str::<EngineOptions>(r#"{"extra_flags":"--log-file page.png"}"#).is_err());
        for json in [r#"{"batch_size":0}"#, r#"{"ubatch_size":8192}"#, r#"{"image_max_tokens":1}"#, r#"{"flash_attention":"invalid"}"#] {
            assert!(serde_json::from_str::<EngineOptions>(json).unwrap().validate().is_err());
        }
    }
}
