use livekit::{Room, RoomOptions};
use std::sync::Arc;

pub struct LivekitManager {
    room: Option<Arc<Room>>,
}

impl LivekitManager {
    pub fn new() -> Self {
        Self { room: None }
    }

    pub async fn connect(
        &mut self,
        url: &str,
        token: &str,
    ) -> Result<(), String> {
        // Connect to LiveKit Room
        let (room, mut events) = Room::connect(url, token, RoomOptions::default())
            .await
            .map_err(|e| e.to_string())?;

        self.room = Some(Arc::new(room));

        // Spawn task to handle room events (e.g., TrackSubscribed, DataReceived)
        tokio::spawn(async move {
            while let Some(event) = events.recv().await {
                match event {
                    livekit::RoomEvent::DataReceived { payload, .. } => {
                        // TODO: Handle text messages from DataChannel for "边说边出字"
                        if let Ok(text) = String::from_utf8(payload.to_vec()) {
                            println!("DataReceived: {}", text);
                            // Emit Tauri event here using app handle (needs refactor to pass app handle)
                        }
                    }
                    livekit::RoomEvent::TrackSubscribed { track, .. } => {
                        // TODO: Handle remote audio track (WebRTC -> rodio playback)
                        println!("Subscribed to track: {:?}", track.sid());
                    }
                    _ => {}
                }
            }
        });

        // TODO: Setup local audio track (cpal mic -> Opus -> WebRTC)
        // and publish to the room.

        Ok(())
    }

    pub async fn disconnect(&mut self) {
        if let Some(room) = self.room.take() {
            room.close().await.ok();
        }
    }
}
