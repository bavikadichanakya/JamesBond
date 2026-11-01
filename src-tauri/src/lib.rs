//! NEXUS Desktop Shell - Native Tauri 2 Application
//! Manages Python backend lifecycle, readiness handshake, window lifecycle, and secure shutdown.

use std::fs;
use std::io::Read;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BackendProcessState {
    child: Option<Child>,
    port: u16,
    auth_token: Option<String>,
}

fn find_workspace_root() -> PathBuf {
    let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if current_dir.join("nexus").exists() {
        return current_dir;
    }
    if let Some(parent) = current_dir.parent() {
        if parent.join("nexus").exists() {
            return parent.to_path_buf();
        }
    }
    PathBuf::from("A:\\Mixer")
}

fn check_tcp_port_ready(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    let addr = format!("127.0.0.1:{}", port);
    while start.elapsed() < timeout {
        if TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(300)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn send_authenticated_shutdown(port: u16, auth_token: &str) {
    let addr = format!("127.0.0.1:{}", port);
    if let Ok(mut stream) = TcpStream::connect(&addr) {
        let request = format!(
            "POST /api/system/shutdown HTTP/1.1\r\n\
             Host: 127.0.0.1:{}\r\n\
             X-Nexus-Auth-Token: {}\r\n\
             Content-Length: 0\r\n\
             Connection: close\r\n\r\n",
            port, auth_token
        );
        let _ = std::io::Write::write_all(&mut stream, request.as_bytes());
        std::thread::sleep(Duration::from_millis(200));
    }
}

fn load_instance_token(workspace: &Path) -> Option<String> {
    let meta_file = workspace.join(".nexus_desktop_instance.json");
    if meta_file.exists() {
        if let Ok(mut file) = fs::File::open(&meta_file) {
            let mut content = String::new();
            if file.read_to_string(&mut content).is_ok() {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                    if let Some(token) = json.get("auth_token").and_then(|t| t.as_str()) {
                        return Some(token.to_string());
                    }
                }
            }
        }
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_state = Arc::new(Mutex::new(BackendProcessState {
        child: None,
        port: 5000,
        auth_token: None,
    }));

    let state_for_setup = Arc::clone(&backend_state);
    let state_for_exit = Arc::clone(&backend_state);

    let app = tauri::Builder::default()
        .setup(move |_app| {
            let workspace = find_workspace_root();
            let port = 5000;
            let current_pid = std::process::id();

            log::info!("[NEXUS Desktop] Initializing shell from workspace: {:?}", workspace);

            // Check if backend already active
            if check_tcp_port_ready(port, Duration::from_millis(500)) {
                log::info!("[NEXUS Desktop] Backend already responsive on port {}.", port);
                let token = load_instance_token(&workspace);
                let mut state = state_for_setup.lock().unwrap();
                state.auth_token = token;
                return Ok(());
            }

            // Spawn managed Python backend
            let script_path = workspace.join("nexus").join("desktop_backend.py");
            log::info!("[NEXUS Desktop] Spawning managed backend: {:?}", script_path);

            let mut cmd = Command::new("python");
            cmd.arg(&script_path)
                .arg("--host")
                .arg("127.0.0.1")
                .arg("--port")
                .arg(port.to_string())
                .arg("--parent-pid")
                .arg(current_pid.to_string())
                .current_dir(&workspace);

            #[cfg(windows)]
            {
                cmd.creation_flags(CREATE_NO_WINDOW);
            }

            match cmd.spawn() {
                Ok(child) => {
                    log::info!("[NEXUS Desktop] Child process spawned (PID: {}). Waiting for readiness...", child.id());
                    {
                        let mut state = state_for_setup.lock().unwrap();
                        state.child = Some(child);
                    }

                    // Handshake poll
                    if check_tcp_port_ready(port, Duration::from_secs(20)) {
                        log::info!("[NEXUS Desktop] Backend readiness confirmed on http://127.0.0.1:{}", port);
                        let token = load_instance_token(&workspace);
                        let mut state = state_for_setup.lock().unwrap();
                        state.auth_token = token;
                    } else {
                        log::error!("[NEXUS Desktop] Timed out waiting for backend readiness on port {}", port);
                    }
                }
                Err(err) => {
                    log::error!("[NEXUS Desktop] Failed to spawn Python backend: {}", err);
                }
            }

            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                log::info!("[NEXUS Desktop] Window close requested. Shutting down managed backend...");
                let mut state = state_for_exit.lock().unwrap();
                if let Some(token) = &state.auth_token {
                    send_authenticated_shutdown(state.port, token);
                }
                if let Some(mut child) = state.child.take() {
                    let _ = child.kill();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |_app_handle, event| {
        if let RunEvent::Exit = event {
            log::info!("[NEXUS Desktop] Application exiting.");
        }
    });
}
