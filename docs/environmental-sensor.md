# Sensor ambiental ESP8266

## Objetivo

El primer prototipo ambiental mide temperatura y humedad dentro de la vivienda.
Utiliza ESPHome para publicar las lecturas en la LAN y las integra con la pila
existente de Prometheus, Grafana y Homepage.

## Hardware

- Placa WeMos D1 mini compatible con ESP8266.
- Shield DHT11 para WeMos D1 mini.
- Cable micro-USB de datos para la primera instalacion.
- Fuente USB de 5 V para el funcionamiento permanente.

El shield conecta la senal del DHT11 a `D4` (`GPIO2`). La placa se alimenta por
su conector micro-USB; no se debe alimentar simultaneamente por pines externos.

## Firmware

La configuracion se encuentra en
[`sensors/sensor-prototipo/sensor-prototipo.yaml`](../sensors/sensor-prototipo/sensor-prototipo.yaml).
Las credenciales Wi-Fi y la contrasena OTA se leen desde `secrets.yaml`, que
esta excluido de Git. `secrets.example.yaml` documenta solamente las claves
necesarias.

Validacion y primera carga por USB:

```powershell
python -m esphome config sensor-prototipo.yaml
python -m esphome run sensor-prototipo.yaml --device COM5
```

Las actualizaciones posteriores pueden enviarse por OTA:

```powershell
python -m esphome run sensor-prototipo.yaml --device <SENSOR_IP>
```

## Flujo de metricas

ESPHome publica `/metrics` en el puerto HTTP del nodo. Prometheus utiliza un
trabajo independiente para consultarlo:

```yaml
- job_name: sensor-prototipo
  scrape_interval: 5s
  static_configs:
    - targets:
        - <SENSOR_IP>:80
```

Consultas utilizadas en Grafana:

```promql
esphome_sensor_value{job="sensor-prototipo", id="temperatura_prototipo"}
```

```promql
esphome_sensor_value{job="sensor-prototipo", id="humedad_prototipo"}
```

`up{job="sensor-prototipo"}` vale `1` cuando Prometheus puede alcanzar el nodo
y `0` cuando pierde alimentacion, Wi-Fi o conectividad.

Homepage no accede directamente a Prometheus. El exportador
`export-homelab-status` consulta solo las dos series necesarias y escribe un
JSON saneado con temperatura y humedad.

## Red y seguridad

- La direccion del nodo se reserva mediante DHCP para evitar cambios.
- El servidor web del ESP se mantiene exclusivamente en la LAN.
- No se publica mediante Caddy ni se expone a Internet.
- Las credenciales Wi-Fi, contrasenas OTA, direcciones MAC e IP reales no se
  incluyen en el repositorio.
- La contrasena OTA debe ser larga, aleatoria y diferente de la del Wi-Fi.

## Limitaciones del prototipo

El DHT11 tiene poca precision y puede registrar una temperatura superior a la
ambiental por estar cerca del ESP8266. Para mejorar las lecturas conviene usar
una caja ventilada, separar fisicamente el sensor de la placa y sustituirlo por
un SHT31-D en la siguiente iteracion.

## Diagnostico

Comprobar el objetivo desde Prometheus:

```bash
curl -fsSG \
  --data-urlencode 'query=up{job="sensor-prototipo"}' \
  http://127.0.0.1:9090/api/v1/query
```

Si devuelve `0`, se comprueban en este orden la alimentacion, el cable USB, la
cobertura Wi-Fi y la reserva DHCP. Homepage puede conservar la ultima lectura
durante unos segundos, por lo que `up` es la referencia para confirmar el
estado real.
