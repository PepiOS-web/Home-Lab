# Red estatica y Docker - 11 de septiembre de 2026

## Red estatica

Se sustituyo la asignacion DHCP de la interfaz Wi-Fi por una configuracion IPv4 estatica mediante Netplan. Se validaron la sintaxis, la ruta predeterminada, el acceso a Internet y la resolucion DNS.

Despues de reiniciar se confirmo que:

- La interfaz Wi-Fi conservaba la direccion configurada.
- La ruta predeterminada apuntaba al router local.
- El HDD seguia montado automaticamente en `/srv/data`.

La direccion concreta, la MAC, el SSID y las credenciales de red no se publican. Queda pendiente reservar o excluir la direccion en el servidor DHCP del router para evitar conflictos futuros.

## Siguiente paso

## Docker

Se instalaron Docker Engine, containerd, Buildx y el complemento Docker Compose desde el repositorio oficial de Docker. Se confirmaron el estado activo del servicio, su inicio automatico y la ejecucion correcta del contenedor efimero `hello-world`.

Por el momento los comandos administrativos de Docker se ejecutan con `sudo`. No se ha concedido acceso al socket de Docker al usuario sin privilegios, ya que dicho acceso es practicamente equivalente a disponer de permisos de administrador.

## Siguiente paso

Preparar la estructura de datos persistentes y desplegar el primer servicio monitorizado.
