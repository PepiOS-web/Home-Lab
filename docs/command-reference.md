# Guia de comandos del HomeLab

Referencia practica para administrar HomeLab Guardian. Los valores entre `< >` son marcadores que deben sustituirse localmente. Nunca deben copiarse contrasenas, claves, direcciones MAC o datos privados al repositorio.

## Indice rapido

- Metodo operativo y seguridad al modificar archivos.
- Diferencias entre PowerShell, CMD y Bash.
- SSH, navegacion, sistema, red, discos y firewall.
- systemd, temporizadores y registros.
- Docker, Compose y montajes.
- Homepage, Prometheus, Grafana y Caddy.
- ESP8266, ESPHome, DHT11, USB y OTA.
- Backups, restauracion y actualizaciones.
- Git y publicacion segura.
- Diagnostico por sintomas.

## Quince comandos fundamentales

```bash
pwd                                      # directorio actual
ls -la                                   # archivos y permisos
cd /ruta                                 # cambiar de directorio
less archivo                             # leer sin modificar
sudo cp origen destino                   # crear una copia
sudo nano archivo                        # editar
grep -n 'texto' archivo                  # buscar
ip -br address                           # interfaces de red
sudo ss -tulpn                           # puertos en escucha
sudo systemctl status servicio           # estado de systemd
sudo journalctl -u servicio -n 50        # registros
sudo docker ps                           # contenedores
sudo docker logs --since 5m contenedor   # registros Docker
curl -v --max-time 5 URL                 # probar HTTP
git status                               # estado del repositorio
```

Estos comandos se memorizan con la practica. Las opciones menos frecuentes se
consultan en este manual o con `--help`.

## Metodo operativo

No es necesario memorizar comandos completos. Para cualquier cambio se sigue
siempre el mismo ciclo:

```text
1. Observar el estado actual
2. Localizar el archivo o servicio responsable
3. Crear una copia de seguridad
4. Realizar un cambio pequeno
5. Validar la sintaxis
6. Aplicar o recargar
7. Comprobar el resultado real
8. Documentar y versionar
```

Preguntas que deben responderse antes de modificar algo:

```text
¿En que terminal estoy?
¿Que componente controla este comportamiento?
¿Que archivo voy a modificar?
¿Como valido el archivo antes de aplicarlo?
¿Como confirmo que el cambio funciona?
¿Donde esta la copia para volver atras?
```

Plantilla segura para configuraciones:

```bash
sudo sed -n '1,240p' /ruta/configuracion
sudo cp /ruta/configuracion /ruta/configuracion.before-cambio
sudo nano /ruta/configuracion
<COMANDO_DE_VALIDACION>
<COMANDO_DE_APLICACION>
<COMANDO_DE_COMPROBACION>
```

No confundir estos resultados:

- `validacion correcta`: la sintaxis es valida, pero todavia puede existir un
  problema de red, permisos o ejecucion.
- `contenedor iniciado`: el proceso arranco, pero el servicio puede no estar
  disponible.
- `ping correcto`: el equipo responde, pero el puerto concreto puede estar
  cerrado.
- `valor visible`: puede ser una lectura antigua; comprobar tambien su marca
  temporal y la metrica `up`.

## Distinguir los terminales

```text
PS C:\Users\usuario>       PowerShell de Windows
usuario@homelab:~$         Terminal del servidor Ubuntu
```

Los comandos de PowerShell se ejecutan en el ordenador personal. Los comandos Bash se ejecutan despues de conectarse al servidor.

Equivalencia de ping:

```powershell
# Windows
ping -n 3 <DESTINO>
```

```bash
# Linux
ping -c 3 <DESTINO>
```

Un comando Bash como `ping -c` no funciona en CMD o PowerShell. Un comando de
PowerShell como `Test-NetConnection` no funciona en Ubuntu.

## Recuperar comandos anteriores y consultar ayuda

Mostrar el historial de Bash:

```bash
history
history | grep docker
history | grep prometheus
```

Buscar interactivamente en el historial:

```text
Ctrl+R     Buscar hacia atras
Ctrl+C     Cancelar la busqueda
```

Consultar ayuda:

```bash
<COMANDO> --help
man <COMANDO>
```

Dentro de `man`:

```text
/texto     Buscar
n          Siguiente coincidencia
q          Salir
```

## Acceso SSH

Conectar mediante el alias configurado en Windows:

```powershell
ssh homelab
```

Conectar indicando usuario e IP:

```powershell
ssh <USUARIO>@<SERVER_IP>
```

Comprobar acceso no interactivo con clave:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=8 homelab "printf 'SSH_OK'"
```

Activar el agente SSH de Windows desde PowerShell como administrador:

```powershell
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
Get-Service ssh-agent
```

Cargar la clave desde PowerShell normal:

```powershell
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
ssh-add -l
```

No publicar la clave privada ni su huella. La clave publica se instala en `~/.ssh/authorized_keys` y debe conservar estos permisos:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Diagnosticar un rechazo de clave sin mostrar su contenido:

```bash
sudo journalctl -u ssh --since "5 minutes ago" --no-pager | tail -30
namei -l "$HOME/.ssh/authorized_keys"
```

Cerrar la conexion:

```bash
exit
```

Abrir un tunel temporal hacia un panel que solo escucha en el servidor:

```powershell
ssh -N -L <PUERTO_LOCAL>:127.0.0.1:<PUERTO_SERVIDOR> homelab
```

El tunel permanece activo mientras esa ventana siga abierta. Se cierra con `Ctrl+C`.

## Navegacion por archivos

Mostrar el directorio actual:

```bash
pwd
```

Listar contenido:

```bash
ls
ls -la
```

Entrar en un directorio y volver al anterior:

```bash
cd /srv/data
cd ..
cd ~
```

Rutas importantes:

```text
/home/usuario                  Directorio personal
/srv/data                      HDD de datos persistentes
/srv/data/compose              Archivos Docker Compose
/srv/data/appdata              Datos persistentes de aplicaciones
/srv/data/backups              Copias de seguridad
/srv/data/shared               Archivos compartidos
/etc/netplan                   Configuracion de red
/etc/fstab                     Montajes persistentes
/var/log                       Registros del sistema
```

Mostrar una estructura limitada de directorios:

```bash
find /srv/data -maxdepth 2 -type d
```

Crear directorios:

```bash
mkdir directorio
mkdir -p ruta/directorio
```

Copiar, mover y renombrar:

```bash
cp origen destino
cp -a directorio-origen directorio-destino
mv nombre-anterior nombre-nuevo
```

Eliminar un directorio vacio:

```bash
rmdir directorio
```

> `rm`, especialmente con `-r`, puede borrar datos de forma irreversible. Verificar siempre `pwd`, `ls` y la ruta completa antes de utilizarlo.

## Consultar y editar archivos

Mostrar un archivo:

```bash
cat archivo
less archivo
```

En `less`, usar las flechas para desplazarse y `q` para salir.

Editar con Nano:

```bash
nano archivo
sudo nano /ruta/protegida/archivo
```

En Nano:

```text
Ctrl+O    Guardar
Enter     Confirmar el nombre
Ctrl+X    Salir
Ctrl+W    Buscar
```

Crear una copia antes de modificar una configuracion:

```bash
sudo cp /ruta/configuracion /ruta/configuracion.backup
```

Crear una copia con fecha para no sobrescribir respaldos anteriores:

```bash
backup_file="/ruta/configuracion.before-$(date +%Y%m%d-%H%M%S)"
sudo cp /ruta/configuracion "$backup_file"
echo "$backup_file"
```

Mostrar numeros de linea y buscar una seccion:

```bash
sudo grep -n -A10 -B3 'texto' /ruta/archivo
sudo sed -n '1,240p' /ruta/archivo
```

Anadir un bloque literal al final de un archivo:

```bash
sudo tee -a /ruta/archivo >/dev/null <<'EOF'
contenido literal
EOF
```

Todo lo situado entre `EOF` se escribe en el archivo. No pegar directamente
la sintaxis de Caddy, YAML o Compose en el prompt: Bash intentaria ejecutarla
como comandos. Para reemplazar un archivo completo, usar `sudo nano` o
`sudo tee /ruta/archivo`, siempre despues de crear una copia.

Comprobar diferencias entre archivo actual y copia:

```bash
sudo diff -u /ruta/configuracion.backup /ruta/configuracion
```

## Informacion del sistema

Version del sistema y kernel:

```bash
cat /etc/os-release
uname -a
```

Tiempo encendido y carga:

```bash
uptime
```

CPU y memoria:

```bash
lscpu
free -h
top
```

Salir de `top` con `q`.

Temperaturas:

```bash
sensors
```

Espacio de almacenamiento:

```bash
df -h
df -h /srv/data
lsblk -f
```

## Red

Mostrar interfaces y direcciones:

```bash
ip -br address
ip -br address show wlp2s0
```

Mostrar rutas:

```bash
ip route
```

Probar acceso a una IP y resolucion DNS:

```bash
ping -c 3 <GATEWAY_IP>
ping -c 3 1.1.1.1
ping -c 3 ubuntu.com
```

Consultar vecinos descubiertos en la red local:

```bash
ip neigh
```

Mostrar puertos TCP y UDP en escucha:

```bash
sudo ss -tulpn
```

Validar y probar cambios de Netplan:

```bash
sudo netplan generate
sudo netplan try
```

`netplan try` revierte los cambios si no se confirman antes de finalizar la cuenta atras. Los cambios de IP deben prepararse preferiblemente desde la consola fisica.

## Servicios y registros

Consultar si un servicio esta activo y habilitado al arrancar:

```bash
systemctl is-active <SERVICIO>
systemctl is-enabled <SERVICIO>
```

Ver informacion detallada:

```bash
sudo systemctl status <SERVICIO>
```

Iniciar, detener y reiniciar:

```bash
sudo systemctl start <SERVICIO>
sudo systemctl stop <SERVICIO>
sudo systemctl restart <SERVICIO>
```

Consultar registros recientes:

```bash
sudo journalctl -u <SERVICIO> -n 50 --no-pager
sudo journalctl -u <SERVICIO> -f
```

`-f` sigue los registros en tiempo real y se detiene con `Ctrl+C`.

Mostrar la unidad efectiva y sus temporizadores:

```bash
sudo systemctl cat <SERVICIO>.service
sudo systemctl cat <SERVICIO>.timer
systemctl list-timers --all | grep <SERVICIO>
```

Despues de modificar una unidad o temporizador:

```bash
sudo systemctl daemon-reload
sudo systemctl restart <SERVICIO>.timer
sudo systemctl start <SERVICIO>.service
```

Un servicio `oneshot` puede aparecer como `inactive (dead)` despues de
finalizar correctamente. Revisar `status=0/SUCCESS` y el registro en lugar de
esperar que permanezca activo.

## Firewall UFW

Consultar reglas:

```bash
sudo ufw status verbose
sudo ufw status numbered
```

Permitir SSH:

```bash
sudo ufw allow OpenSSH
```

Permitir un puerto solo desde la red local:

```bash
sudo ufw allow from <LAN_CIDR> to any port <PUERTO> proto tcp
```

No abrir paneles directamente a Internet. Docker puede gestionar reglas de red que requieren una revision adicional a UFW.

## Discos y montajes

Identificar discos, modelos y puntos de montaje:

```bash
lsblk -o NAME,SIZE,MODEL,FSTYPE,MOUNTPOINTS
findmnt /srv/data
```

Consultar salud SMART:

```bash
sudo smartctl -a /dev/<DISCO>
sudo smartctl -l selftest /dev/<DISCO>
```

Iniciar pruebas SMART:

```bash
sudo smartctl -t short /dev/<DISCO>
sudo smartctl -t long /dev/<DISCO>
```

> Operaciones como `mkfs`, `wipefs`, `fdisk` o `parted` pueden destruir datos. No ejecutarlas sin comprobar previamente modelo, tamano, montaje y dispositivo exactos.

## Docker

Comprobar Docker y Compose:

```bash
sudo systemctl is-active docker
sudo systemctl is-enabled docker
sudo docker --version
sudo docker compose version
```

Listar contenedores activos o todos:

```bash
sudo docker ps
sudo docker ps -a
```

Ver registros:

```bash
sudo docker logs --tail 50 <CONTENEDOR>
sudo docker logs -f <CONTENEDOR>
```

Consultar salud de un contenedor:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' <CONTENEDOR>
```

Validar un archivo Compose:

```bash
sudo docker compose -f /ruta/compose.yaml config
```

Crear o actualizar un servicio:

```bash
sudo docker compose -f /ruta/compose.yaml up -d
```

Recrear un contenedor cuando se modifican puertos, volumenes o variables:

```bash
sudo docker compose -f /ruta/compose.yaml up -d --force-recreate <SERVICIO>
```

`docker restart` reinicia el contenedor existente, pero no aplica cambios en
montajes, puertos o variables definidos por Compose. Para esos cambios es
necesario recrearlo.

Detener una composicion conservando sus datos persistentes:

```bash
sudo docker compose -f /ruta/compose.yaml down
```

Reiniciar un contenedor:

```bash
sudo docker restart <CONTENEDOR>
```

Mostrar nombre y estado de todos los contenedores activos:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Uso de recursos:

```bash
sudo docker stats
sudo docker system df
```

Salir de `docker stats` con `Ctrl+C`.

Mostrar los montajes de un contenedor:

```bash
sudo docker inspect <CONTENEDOR> \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Comprobar un archivo desde dentro de un contenedor:

```bash
sudo docker exec <CONTENEDOR> ls -la /ruta/interna
sudo docker exec <CONTENEDOR> cat /ruta/interna/archivo
```

Si un proceso reemplaza un archivo de forma atomica, no montar solamente ese
archivo en Docker. El contenedor puede conservar el inode antiguo. Montar el
directorio padre como solo lectura permite ver las nuevas versiones:

```yaml
volumes:
  - /ruta/estado:/app/public/estado:ro
```

## Servicios actuales

Uptime Kuma:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' uptime-kuma
sudo docker logs --tail 50 uptime-kuma
sudo docker compose -f /srv/data/compose/uptime-kuma/compose.yaml up -d
```

NetAlertX:

```bash
sudo docker inspect --format '{{.State.Health.Status}}' netalertx
sudo docker logs --tail 50 netalertx
sudo docker compose -f /srv/data/compose/netalertx/compose.yaml up -d
```

Homepage:

```bash
sudo docker restart homepage
sudo docker logs --since 2m homepage
sudo nano /srv/data/appdata/homepage/settings.yaml
sudo nano /srv/data/appdata/homepage/services.yaml
sudo nano /srv/data/appdata/homepage/custom.css
sudo nano /srv/data/appdata/homepage/custom.js
```

Validar y recrear Homepage despues de modificar su Compose:

```bash
sudo docker compose \
  -f /srv/data/compose/homepage/compose.yaml \
  config >/dev/null

sudo docker compose \
  -f /srv/data/compose/homepage/compose.yaml \
  up -d --force-recreate homepage
```

Comprobar el resumen saneado que ve Homepage:

```bash
sudo docker exec homepage \
  wget -qO- http://127.0.0.1:3000/homelab-status/status.json
```

Compararlo con el archivo del servidor:

```bash
sudo grep -E \
  'generated_at|sensor_temperature|sensor_humidity' \
  /srv/data/appdata/homelab-status/status.json
```

Si el archivo del servidor cambia y el del contenedor no, revisar el montaje
con `docker inspect`. Si ambos cambian pero la tarjeta falla, revisar la URL de
`customapi` en `services.yaml` y los registros de Homepage.

Grafana y Prometheus:

```bash
sudo docker compose -f /srv/data/compose/monitoring/compose.yaml config --quiet
sudo docker compose -f /srv/data/compose/monitoring/compose.yaml up -d --force-recreate grafana
sudo docker logs --tail 50 grafana
```

Localizar la configuracion montada de Prometheus:

```bash
sudo docker inspect prometheus \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Validar Prometheus antes de reiniciarlo:

```bash
sudo docker exec prometheus \
  promtool check config /etc/prometheus/prometheus.yml
```

Solo despues de obtener `SUCCESS`:

```bash
sudo docker restart prometheus
```

Consultar una expresion PromQL desde el servidor:

```bash
curl -fsSG \
  --data-urlencode 'query=<CONSULTA_PROMQL>' \
  http://127.0.0.1:9090/api/v1/query
```

No intentar abrir `http://127.0.0.1:9090` directamente en el navegador del
ordenador. En el ordenador, `127.0.0.1` se refiere al propio ordenador, no al
servidor. Para una consulta administrativa temporal se puede usar un tunel SSH.

Comprobar la configuracion efectiva de Grafana sin mostrar secretos:

```bash
sudo docker inspect grafana \
  --format '{{range .Config.Env}}{{println .}}{{end}}' |
grep -E '^GF_SERVER_(DOMAIN|ROOT_URL|SERVE_FROM_SUB_PATH|ENFORCE_DOMAIN)='
```

Grafana se publica bajo `https://portal.home.arpa/grafana/`. Al compartir origen con Homepage, el panel autenticado funciona en navegadores moviles sin habilitar acceso anonimo.

Validar y recargar Caddy:

```bash
sudo docker exec caddy \
  caddy validate \
  --config /etc/caddy/Caddyfile \
  --adapter caddyfile

sudo docker exec caddy \
  caddy reload \
  --config /etc/caddy/Caddyfile \
  --adapter caddyfile
```

Probar una ruta HTTPS cuando el DNS local no esta disponible en el propio servidor:

```bash
curl -ksSI \
  --resolve portal.home.arpa:443:<SERVER_IP> \
  https://portal.home.arpa/grafana/login |
head
```

Una respuesta `HTTP/2 200` confirma que Caddy alcanza Grafana en la subruta.

## Sensor ambiental ESP8266 y ESPHome

### Rutas y variables en Windows

Definir las rutas una vez por sesion de PowerShell:

```powershell
$pythonHomeLab = "<RUTA_PYTHON>\python.exe"
$sensorDir = "<RUTA_REPOSITORIO>\sensors\sensor-prototipo"
$sensorYaml = "$sensorDir\sensor-prototipo.yaml"
```

Comprobar ESPHome:

```powershell
& $pythonHomeLab -m esphome version
& $pythonHomeLab -m esphome config $sensorYaml
```

### Detectar el puerto USB

```powershell
Get-PnpDevice -PresentOnly -Class Ports |
    Select-Object Status, FriendlyName
```

Alternativa:

```powershell
[System.IO.Ports.SerialPort]::GetPortNames()
```

El clon WeMos utiliza normalmente un conversor CH340. El numero `COM` puede
cambiar al utilizar otro puerto USB.

Si el puerto esta ocupado:

```powershell
Get-Process python, pythonw -ErrorAction SilentlyContinue
```

Cerrar primero monitores serie o procesos ESPHome que ya no se necesiten. No
pueden utilizar el mismo puerto dos programas simultaneamente.

### Primera instalacion por USB

```powershell
& $pythonHomeLab -m esphome run $sensorYaml --device <COM_PORT>
```

Resultado esperado:

```text
Successfully uploaded program
```

Salir del monitor con `Ctrl+C`. En `miniterm`, la salida indicada es
`Ctrl+]`, pero `Ctrl+C` detiene normalmente el comando de ESPHome.

### Actualizacion OTA

```powershell
& $pythonHomeLab -m esphome run $sensorYaml --device <SENSOR_IP>
```

Resultado esperado:

```text
OTA successful
Successfully uploaded program
```

Si aparece `Authentication invalid`, el firmware instalado contiene una
contrasena OTA distinta de `secrets.yaml`. Realizar una carga por USB para
sincronizarla; no publicar ni recuperar la contrasena antigua.

### Registros serie

```powershell
& $pythonHomeLab -m esphome logs $sensorYaml --device <COM_PORT>
```

El arranque del ESP8266 puede emitir caracteres ilegibles antes de que el
logger cambie a 115200 baudios. Esto es normal. Buscar despues:

```text
Connected
IP Address
Temperature
Humidity
```

### Comprobar conectividad desde Windows

```powershell
Test-NetConnection <SENSOR_IP> -Port 80
Test-NetConnection <SENSOR_IP> -Port 8266
```

- Puerto `80`: interfaz web y metricas.
- Puerto `8266`: actualizaciones OTA.

### Comprobar el sensor desde el servidor

```bash
curl -fsS --max-time 5 http://<SENSOR_IP>/metrics |
grep -E 'temperatura_prototipo|humedad_prototipo'
```

Estado de recogida en Prometheus:

```bash
curl -fsSG \
  --data-urlencode 'query=up{job="sensor-prototipo"}' \
  http://127.0.0.1:9090/api/v1/query
```

Interpretacion:

```text
"1"    Prometheus alcanza el sensor
"0"    Sensor sin alimentacion, sin Wi-Fi o no accesible
vacio  El trabajo no se ha cargado o aun no se ha recogido
```

Consultar temperatura y humedad:

```bash
curl -fsSG \
  --data-urlencode 'query=esphome_sensor_value{job="sensor-prototipo",id="temperatura_prototipo"}' \
  http://127.0.0.1:9090/api/v1/query

curl -fsSG \
  --data-urlencode 'query=esphome_sensor_value{job="sensor-prototipo",id="humedad_prototipo"}' \
  http://127.0.0.1:9090/api/v1/query
```

### Diagnostico por capas del sensor

```text
1. Alimentacion: LED, cable y cargador USB de 5 V
2. Firmware: registros serie y lecturas DHT11
3. Wi-Fi: mensaje Connected y direccion reservada
4. Red: ping y puerto 80
5. ESPHome: /metrics devuelve valores
6. Prometheus: up vale 1
7. Grafana: consulta muestra el valor actual
8. Exportador: status.json cambia
9. Homepage: ve el mismo JSON y actualiza la tarjeta
```

No empezar reiniciando todos los servicios. Comprobar cada capa hasta localizar
la primera que falla.

### Precauciones fisicas

- Alimentar la placa mediante un cargador USB de 5 V en buen estado.
- No alimentar simultaneamente por USB y por pines externos.
- Desconectar la alimentacion antes de medir continuidad.
- Un pitido continuo y cercano a `0 ohm` entre alimentacion y tierra indica un
  posible cortocircuito; no conectar la placa hasta corregirlo.
- Si un regulador o integrado quema al tocarlo, desconectar inmediatamente.
- No dejar el prototipo descubierto sobre tejidos o materiales inflamables.
- El DHT11 sobre la placa puede medir el calor del ESP8266 y no solo el ambiente.

## Git y publicacion segura

### Flujo diario

```bash
git status
git diff
git diff --check
git add <ARCHIVOS>
git commit -m "tipo: descripcion breve"
git push origin main
```

Antes de publicar, comprobar sincronizacion:

```bash
git fetch origin
git rev-list --left-right --count origin/main...main
```

`0 0` indica que ambas ramas estaban sincronizadas antes del nuevo commit.

Comprobar que un secreto esta ignorado:

```bash
git check-ignore -v sensors/sensor-prototipo/secrets.yaml
git check-ignore -v sensors/sensor-prototipo/.esphome/
```

Buscar accidentalmente datos sensibles antes de confirmar:

```bash
rg -n --hidden \
  -g '!**/.git/**' \
  -g '!**/.esphome/**' \
  -g '!**/secrets.yaml' \
  'password|token|secret|<DATO_PRIVADO>' .
```

Revisar cada coincidencia: palabras como `password` pueden ser referencias a
`!secret` o marcadores seguros. Nunca publicar:

- `secrets.yaml`.
- `.env` reales.
- claves privadas.
- contrasenas Wi-Fi u OTA.
- tokens.
- IP o MAC reales del despliegue.
- capturas con SSID, BSSID, IP publica o credenciales.

En archivos publicos utilizar `<SERVER_IP>`, `<SENSOR_IP>`, `<WIFI_SSID>` y
otros marcadores descriptivos.

### Comprobar el estado final

```bash
git status --short
git log -1 --oneline --decorate
```

Una salida vacia de `git status --short` indica que no quedan cambios locales
pendientes.

## Diagnostico rapido por sintomas

### Un panel web no abre

```text
1. Resolver el nombre DNS
2. Probar ping si corresponde
3. Probar el puerto con curl o Test-NetConnection
4. Revisar el contenedor
5. Revisar sus registros
6. Revisar Caddy y la ruta de proxy
```

```bash
sudo docker ps
sudo docker logs --since 5m <CONTENEDOR>
curl -v --max-time 5 http://127.0.0.1:<PUERTO>/
```

### Grafana vuelve al inicio de sesion

Comprobar que dominio, URL raiz, subruta y cookies coinciden con la URL que usa
el navegador. No habilitar acceso anonimo para solucionar un problema de
cookies.

### Prometheus devuelve un resultado vacio

- Esperar al menos un intervalo de `scrape_interval` despues del reinicio.
- Comprobar que el trabajo aparece en `/api/v1/targets`.
- Consultar `up{job="<JOB>"}`.
- Verificar desde el servidor el endpoint original con `curl`.

### Homepage muestra valores antiguos

Comparar, en este orden:

```bash
sudo grep -E 'generated_at|sensor_' \
  /srv/data/appdata/homelab-status/status.json

sudo docker exec homepage \
  wget -qO- http://127.0.0.1:3000/homelab-status/status.json |
grep -E 'generated_at|sensor_'
```

- Si el primer archivo no cambia: revisar servicio y temporizador.
- Si el primero cambia y el segundo no: revisar el montaje Docker.
- Si ambos cambian: revisar `services.yaml`, `refreshInterval` y los registros
  de Homepage.

### El sensor web no carga

```bash
curl -v --max-time 5 http://<SENSOR_IP>/
```

`No route to host` junto con `up=0` indica normalmente perdida de alimentacion,
cobertura Wi-Fi o conectividad. Probar primero en la ubicacion anterior con un
cable y cargador conocidos antes de modificar Prometheus o Homepage.

## Copias de seguridad del servidor

Consultar el temporizador y ejecutar una copia manual:

```bash
systemctl status homelab-backup.timer --no-pager
systemctl list-timers --all | grep homelab-backup
sudo systemctl start homelab-backup.service
```

Verificar el resultado:

```bash
systemctl status homelab-backup.service --no-pager
sudo journalctl -u homelab-backup.service -n 40 --no-pager
sudo ls -lh /srv/data/backups/daily
```

El servicio es `oneshot`: `inactive (dead)` es normal despues de finalizar. El resultado valido es `status=0/SUCCESS` y la suma debe indicar `OK`.

Verificar manualmente la suma del ultimo backup:

```bash
cd /srv/data/backups/daily
latest=$(find . -maxdepth 1 -type f -name 'homelab-*.tar.gz' -printf '%T@ %f\n' | sort -nr | awk 'NR == 1 { print $2 }')
sudo sha256sum -c "${latest}.sha256"
```

## Copia externa cifrada en Windows

La copia externa usa `restic`. El servidor conserva copias diarias y el ordenador obtiene una copia semanal cifrada. Los archivos sin cifrar se descargan solo a un directorio temporal fuera de OneDrive y se eliminan al finalizar.

Ejecutar manualmente la copia externa:

```powershell
powershell.exe `
  -NoProfile `
  -ExecutionPolicy Bypass `
  -File "$env:USERPROFILE\OneDrive\Desktop\HomeLab-Backups\Backup-HomeLab.ps1"
```

Consultar la tarea semanal:

```powershell
Get-ScheduledTask -TaskName "HomeLab Encrypted Backup"
Get-ScheduledTaskInfo -TaskName "HomeLab Encrypted Backup"
```

Ejecutarla inmediatamente y consultar el resultado:

```powershell
Start-ScheduledTask -TaskName "HomeLab Encrypted Backup"
Get-ScheduledTaskInfo -TaskName "HomeLab Encrypted Backup"
```

`LastTaskResult` igual a `0` indica exito. La tarea esta programada semanalmente y usa `StartWhenAvailable` para ejecutarse despues si el ordenador no estaba disponible.

Comprobar que no quedaron archivos temporales sin cifrar:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\HomeLabBackup\staging" -Force
```

La contrasena original de `restic` debe guardarse en un gestor de contrasenas. El archivo DPAPI permite automatizar el proceso solo con el mismo usuario de Windows, pero no sustituye la contrasena para una recuperacion en otro equipo.

## Restauracion de prueba

Una copia no se considera verificada hasta demostrar que puede restaurarse. La prueba debe hacerse en una carpeta temporal y nunca sobre el servidor activo.

Despues de restaurar el ultimo snapshot con `restic`, comprobar el archivo:

```powershell
tar -tzf "<RUTA_TEMPORAL>\homelab-<FECHA>.tar.gz" |
Select-String "srv/data/compose|srv/data/appdata/homepage|etc/ssh"
```

Antes de borrar la prueba, resolver y revisar la ruta exacta:

```powershell
$target = [IO.Path]::GetFullPath("$env:LOCALAPPDATA\HomeLabRestoreTest-current")
$target
```

Solo si coincide exactamente con la carpeta temporal esperada:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\HomeLabRestoreTest-current" -Recurse -Force
```

No borrar ni mover la carpeta `repository` de OneDrive: contiene el repositorio cifrado real.

## Actualizaciones

Actualizar Ubuntu:

```bash
sudo apt update
sudo apt upgrade
```

Antes de actualizar contenedores persistentes se debe realizar una copia de seguridad. El flujo general es:

```bash
sudo docker compose -f /ruta/compose.yaml pull
sudo docker compose -f /ruta/compose.yaml up -d
```

No automatizar actualizaciones de versiones principales sin revisar notas de cambios y copias de seguridad.

## Apagar y reiniciar

```bash
sudo reboot
sudo poweroff
```

`poweroff` requiere volver a encender fisicamente el portatil, salvo que se configure y soporte Wake-on-LAN.

## Comprobacion rapida del HomeLab

```bash
ip -br address
ip route
findmnt /srv/data
df -h /srv/data
sudo ufw status
sudo docker ps
sensors
```

Estos comandos permiten revisar red, almacenamiento, firewall, contenedores y temperaturas sin modificar el sistema.
