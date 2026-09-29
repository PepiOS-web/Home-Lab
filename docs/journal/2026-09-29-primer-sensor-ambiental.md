# 2026-09-29 - Primer sensor ambiental

## Objetivo

Se inicio la fase de sensores fisicos del HomeLab con un primer nodo capaz de
medir temperatura y humedad. El objetivo no era solamente leer un DHT11, sino
validar el recorrido completo desde el entorno fisico hasta el almacenamiento,
la visualizacion y el portal operativo.

```text
DHT11 -> ESP8266 / ESPHome -> Prometheus -> Grafana
                                      `-> resumen saneado -> Homepage
```

## Montaje del prototipo

- Se reutilizo una placa WeMos D1 mini compatible con ESP8266MOD.
- Se utilizo un shield DHT11 para temperatura y humedad.
- Se soldaron cabeceras macho en el shield y cabeceras hembra en la placa para
  mantener el conjunto desmontable.
- Se confirmo que la senal del DHT11 utiliza `D4`, equivalente a `GPIO2`.
- Se verificaron continuidad, tierra y alimentacion antes de conectar USB.
- Se descarto un cortocircuito permanente entre `3V3` y `GND`.
- Se comprobo una alimentacion aproximada de 3,3 V en el shield.
- El conversor USB-serie CH340 fue reconocido correctamente por Windows.

Durante las primeras pruebas se vigilo la temperatura de los reguladores y del
conversor USB. El montaje dejo de calentarse de forma anomala y permanecio
estable antes de continuar con el firmware.

## Firmware ESPHome

- Se instalo ESPHome en un entorno Python local de Windows.
- La primera carga se realizo por USB mediante el puerto serie del CH340.
- El DHT11 quedo configurado en `D4` como modelo explicito `DHT11`.
- El monitor serie confirmo lecturas validas de temperatura y humedad.
- Se incorporaron Wi-Fi, servidor web, exportacion Prometheus y OTA protegida.
- Las credenciales se trasladaron a `secrets.yaml` y se excluyeron de Git.
- Se creo `secrets.example.yaml` con marcadores publicables.
- El intervalo de lectura se redujo finalmente a cinco segundos para el
  prototipo.

La primera actualizacion OTA fallo porque la contrasena del archivo local no
coincidia con la almacenada en el firmware. Una nueva carga por USB sincronizo
la credencial y permitio utilizar OTA en las actualizaciones posteriores.

## Red

- El nodo se conecto a la red Wi-Fi de 2,4 GHz.
- Se comprobo el servidor web y el puerto OTA desde Windows.
- Se creo una reserva DHCP para conservar una direccion estable.
- Se verifico desde el servidor que `/metrics` devolvia las dos lecturas y sus
  indicadores de fallo.

La resolucion mDNS `.local` no funciono inicialmente en Windows. Los registros
serie permitieron localizar el nodo y la reserva DHCP elimino la dependencia
de esa resolucion para Prometheus.

No se publica la direccion IP, MAC, SSID, BSSID ni ninguna credencial real.

## Prometheus y Grafana

- Se creo un trabajo `sensor-prototipo` en Prometheus.
- El intervalo de recogida se establecio en cinco segundos.
- `promtool` valido la configuracion antes de reiniciar Prometheus.
- La metrica `up{job="sensor-prototipo"}` confirmo la disponibilidad del nodo.
- Se comprobaron por API las series de temperatura y humedad.
- Grafana recibio indicadores instantaneos e historicos para ambas medidas.

Un resultado vacio inmediatamente despues de reiniciar Prometheus no era un
fallo: todavia no habia transcurrido el primer intervalo de recogida. Tras la
primera consulta, `up` aparecio con valor `1`.

## Integracion con Homepage

El exportador de estado se amplio para consultar solamente las dos series
ambientales necesarias y anadirlas al JSON saneado. Homepage muestra los
valores actuales en una seccion `Sensores ambientales` sin obtener acceso
directo a Prometheus.

Se detecto un problema de datos congelados. El exportador sustituye
`status.json` de forma atomica, pero Docker tenia montado el archivo individual.
El contenedor conservaba el inode anterior y seguia mostrando una lectura
antigua aunque el archivo del servidor cambiara.

La solucion consistio en:

- Montar el directorio completo de estado como solo lectura.
- Servir `homelab-status/status.json` dentro de Homepage.
- Actualizar las tres referencias `customapi` a la nueva ruta.
- Recrear el contenedor para aplicar el nuevo montaje.

La comprobacion desde dentro del contenedor devolvio `HTTP 200` y el mismo JSON
actualizado que el servidor.

## Diagnostico de una desconexion

Al mover el prototipo, su pagina dejo de responder. El servidor devolvio
`No route to host` y Prometheus mostro `up=0`. Esto permitio localizar el fallo
antes de modificar las capas superiores. Se revisaron, en orden:

1. Alimentacion y cable USB.
2. Cobertura Wi-Fi en la nueva ubicacion.
3. Acceso al puerto HTTP.
4. Endpoint `/metrics`.
5. Estado `up` en Prometheus.
6. Lecturas en Grafana y Homepage.

El nodo recupero la conectividad sin cambios en Prometheus ni Homepage.

## Seguridad

- El servidor web del ESP permanece exclusivamente en la LAN.
- El nodo no se publica mediante Caddy ni se expone a Internet.
- OTA utiliza una contrasena diferente de la red Wi-Fi.
- `secrets.yaml` y `.esphome/` estan ignorados por Git.
- Los archivos publicos utilizan `<SENSOR_IP>` y otros marcadores.
- Homepage recibe un JSON saneado y no accede al socket Docker ni a los
  registros privados del sistema.
- Antes de publicar se buscaron IP, MAC, SSID, contrasenas y tokens reales.

## Limitaciones y aprendizajes

El DHT11 valida correctamente la arquitectura, pero su precision es limitada.
Al estar muy cerca del ESP8266 puede medir parte del calor de la propia placa.
La siguiente version debera separar fisicamente el sensor, utilizar una caja
ventilada y sustituirlo por un modelo mas preciso como el SHT31-D.

El principal aprendizaje fue diagnosticar el sistema por capas. Confirmar
primero sensor, red, endpoint, Prometheus, exportador y finalmente Homepage
evito reinicios y cambios innecesarios. Tambien se comprobo que una sintaxis
valida o un contenedor arrancado no garantizan por si solos que el recorrido
completo de datos funcione.

## Resultado

El primer nodo ambiental quedo operativo con:

- Lecturas de temperatura y humedad cada cinco segundos.
- Interfaz local de ESPHome.
- Historico en Prometheus y Grafana.
- Valores actuales en Homepage.
- Reserva DHCP.
- Actualizaciones OTA.
- Configuracion, seguridad y diagnostico documentados.

El siguiente objetivo es mejorar la precision fisica del nodo, incorporar un
estado visible de conectado/desconectado y comenzar a evaluar sensores de
calidad del aire.
