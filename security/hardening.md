# Seguridad

## Medidas aplicadas

- Acceso remoto con clave SSH Ed25519 protegida por frase de paso.
- UFW activo con politica predeterminada de denegar conexiones entrantes.
- Solo OpenSSH esta permitido por el momento.
- Sistema actualizado tras la instalacion.

## Pendiente

- Confirmar el acceso por clave desde una segunda sesion antes de desactivar contrasenas SSH.
- Configurar actualizaciones de seguridad automaticas.
- Revisar periodicamente usuarios, puertos y registros.
- Crear una estrategia de copias de seguridad.
- Usar VPN antes de habilitar cualquier acceso desde Internet.

## Informacion que no debe publicarse

- Claves privadas o contenido de `authorized_keys`.
- Contrasenas, tokens y secretos Wi-Fi.
- Archivos `.env` reales.
- IP publica, numeros de serie y direcciones MAC.
