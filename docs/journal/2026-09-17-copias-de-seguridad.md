# Copias de seguridad - 17 de septiembre de 2026

Se creo y verifico una primera copia manual de los datos persistentes y configuraciones. La comprobacion SHA-256 finalizo correctamente, el indice contenia todos los componentes esperados y los contenedores volvieron a un estado saludable.

Despues se implemento un servicio `oneshot` y un temporizador de systemd para realizar copias diarias. La primera ejecucion completa termino con `status=0/SUCCESS`, verifico automaticamente el archivo y reinicio los servicios.

Los backups usan permisos restrictivos y se conservan localmente durante siete dias. Los archivos reales, hashes, bases de datos y contenido privado no forman parte del repositorio.

## Siguiente paso

Crear una segunda copia cifrada fuera del disco del servidor y documentar un procedimiento de restauracion probado.
