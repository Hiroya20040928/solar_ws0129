// ESP32 UDP WiFi Receiver Template for SolarCar Motor Controller
#include <WiFi.h>
#include <WiFiUdp.h>

WiFiUDP udp;
const int localPort = 5006;

void setup() {
  Serial.begin(115200);
  WiFi.begin("SolarCar_WiFi", "YATA2027_Pass");
  while (WiFi.status() != WL_CONNECTED) delay(500);
  udp.begin(localPort);
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize) {
    char buffer[255];
    int len = udp.read(buffer, 255);
    if (len > 0) buffer[len] = 0;
    Serial.println(buffer);
  }
}
