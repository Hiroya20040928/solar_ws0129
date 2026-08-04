#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "REPLACE_ME";
const char* WIFI_PASSWORD = "REPLACE_ME";
const uint16_t LISTEN_PORT = 52002;

WiFiUDP udp;
char packetBuffer[1024];

float speedCmdKmh = 0.0f;
float upperSpeedCmdKmh = 0.0f;
String driveMode = "stop";
unsigned long lastPacketMs = 0;

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
  udp.begin(LISTEN_PORT);
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize > 0 && packetSize < (int)sizeof(packetBuffer)) {
    int len = udp.read(packetBuffer, sizeof(packetBuffer) - 1);
    packetBuffer[len] = '\0';

    StaticJsonDocument<1024> doc;
    DeserializationError err = deserializeJson(doc, packetBuffer);
    if (!err) {
      const char* type = doc["type"] | "";
      if (String(type) == "planner_command") {
        speedCmdKmh = doc["planner"]["speed_cmd_kmh"] | speedCmdKmh;
        upperSpeedCmdKmh = doc["planner"]["upper_speed_cmd_kmh"] | upperSpeedCmdKmh;
        driveMode = String((const char*)(doc["planner"]["drive_mode"] | driveMode.c_str()));
        lastPacketMs = millis();
      }
    }
  }

  const bool timeout = (millis() - lastPacketMs) > 3000UL;
  if (timeout) {
    driveMode = "comm_lost";
  }

  // Replace this with your local control law and local clamp logic.
  Serial.print("speed_cmd_kmh=");
  Serial.print(speedCmdKmh, 1);
  Serial.print(" upper_speed_cmd_kmh=");
  Serial.print(upperSpeedCmdKmh, 1);
  Serial.print(" drive_mode=");
  Serial.println(driveMode);

  delay(50);
}
