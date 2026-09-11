# HomeLab

Proyecto personal para convertir un portatil reutilizado en un servidor domestico seguro, monitorizado y ampliable. El objetivo final es integrar sistemas, redes, ciberseguridad, sensores electronicos y deteccion de anomalias mediante IA.

## Estado actual

- Ubuntu Server 24.04 LTS instalado en el SSD.
- Administracion remota mediante SSH con clave Ed25519.
- Firewall UFW activo y limitado inicialmente a OpenSSH.
- Conexion Wi-Fi operativa tras reinicios.
- Direccion IPv4 local estatica configurada para la administracion del servidor.
- Suspension, hibernacion y accion de cierre de tapa desactivadas.
- Pruebas SMART extendidas completadas sin errores en el SSD y el HDD.
- HDD de 1 TB preparado en ext4 y montado automaticamente en `/srv/data`.

## Hardware base

| Componente | Especificacion |
|---|---|
| Equipo | Acer Aspire VX5-591G reutilizado |
| Procesador | Intel Core i7-7700HQ |
| Memoria | 8 GB RAM |
| Disco del sistema | SSD Kingston de 128 GB |
| Almacenamiento | HDD Toshiba de 1 TB |
| Red | Ethernet y Wi-Fi |

Los numeros de serie, credenciales, direcciones MAC y otros identificadores no se publican.

## Objetivos

1. Construir una base Linux estable y accesible en remoto.
2. Preparar almacenamiento persistente para servicios y copias de seguridad.
3. Desplegar servicios aislados con contenedores.
4. Monitorizar recursos, red, temperaturas y disponibilidad.
5. Incorporar sensores ambientales y electricos.
6. Detectar comportamientos anomalos mediante modelos de IA.

## Documentacion

- [Arquitectura](docs/architecture.md)
- [Hoja de ruta](docs/roadmap.md)
- [Seguridad](security/hardening.md)
- [Problemas y soluciones](docs/troubleshooting.md)
- [Diario de progreso](docs/journal/2026-09-10-instalacion-inicial.md)

## Seguridad del repositorio

Este repositorio nunca debe contener contrasenas, claves SSH privadas, secretos Wi-Fi, tokens, IP publicas ni archivos `.env` reales. Los ejemplos usan valores como `<SERVER_IP>`.

## Licencia

Publicado bajo la licencia MIT.
