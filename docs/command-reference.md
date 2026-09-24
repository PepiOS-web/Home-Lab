# Guia de comandos del HomeLab

Referencia practica para administrar HomeLab Guardian. Los valores entre `< >` son marcadores que deben sustituirse localmente. Nunca deben copiarse contrasenas, claves, direcciones MAC o datos privados al repositorio.

## Distinguir los terminales

```text
PS C:\Users\usuario>       PowerShell de Windows
usuario@homelab:~$         Terminal del servidor Ubuntu
```

Los comandos de PowerShell se ejecutan en el ordenador personal. Los comandos Bash se ejecutan despues de conectarse al servidor.

## Acceso SSH

Conectar mediante el alias configurado en Windows:

```powershell
ssh homelab
```

Conectar indicando usuario e IP:

```powershell
ssh martin@<SERVER_IP>
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

Detener una composicion conservando sus datos persistentes:

```bash
sudo docker compose -f /ruta/compose.yaml down
```

Reiniciar un contenedor:

```bash
sudo docker restart <CONTENEDOR>
```

Uso de recursos:

```bash
sudo docker stats
sudo docker system df
```

Salir de `docker stats` con `Ctrl+C`.

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
