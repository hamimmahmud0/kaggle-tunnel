use std::fs;
use std::path::Path;

fn main() {
    tauri_build::build();

    // Copy the kaggle_tunnel Python package into the Tauri resources directory
    // so the app can find it via find_bundled_kaggle_tunnel() at runtime.
    //
    // Source: ../../src/kaggle_tunnel/ (relative to this build.rs)
    // Target: $OUT_DIR/../../resources/kaggle_tunnel/
    //
    // Tauri bundles the resources/ directory adjacent to the binary in .deb/snap.
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let src_dir = manifest_dir.join("../../src/kaggle_tunnel");
    let resources_dir = manifest_dir.join("resources/kaggle_tunnel");

    if src_dir.exists() {
        fs::create_dir_all(&resources_dir).expect("Failed to create resources/kaggle_tunnel dir");
        copy_dir_recursive(&src_dir, &resources_dir)
            .expect("Failed to copy kaggle_tunnel Python package to resources dir");
        println!("cargo:info=Copied kaggle_tunnel Python package to resources/kaggle_tunnel/");
    } else {
        println!("cargo:warning=Python source not found at ../../src/kaggle_tunnel — skipping bundle");
    }
}

/// Recursively copy a directory, skipping __pycache__ and .pyc files.
fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    if !dst.exists() {
        fs::create_dir_all(dst)?;
    }
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let file_name = entry.file_name();
        let name_str = file_name.to_string_lossy();

        // Skip __pycache__ directories and .pyc files
        if name_str == "__pycache__" || name_str.ends_with(".pyc") {
            continue;
        }

        let file_type = entry.file_type()?;
        let src_path = entry.path();
        let dst_path = dst.join(&file_name);
        if file_type.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            fs::copy(&src_path, &dst_path)?;
        }
    }
    Ok(())
}
