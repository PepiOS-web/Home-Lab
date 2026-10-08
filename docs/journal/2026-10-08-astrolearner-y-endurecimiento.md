# 2026-10-08 - AstroLearner y endurecimiento operativo

## Objetivo

Documentar los nuevos flujos de contenido de AstroLearner, el control manual de
la emisión orbital y las mejoras de seguridad y recuperación incorporadas al
HomeLab.

## AstroLearner Factory

- Se añadió un estudio local para crear borradores de vídeos y tres Shorts a
  partir de fuentes primarias permitidas.
- La generación usa un modelo local servido por Ollama, voz Piper y recursos
  visuales procedurales; no genera vídeo fotorrealista desde texto.
- Los trabajos y sus artefactos se conservan en almacenamiento local. La
  publicación automática está desactivada: cada resultado requiere revisión
  humana antes de subirlo a YouTube.
- El acceso al puerto local se documentó mediante túnel SSH. Los ejemplos no
  contienen el usuario personal ni la IP del servidor.

## AstroLearner ISS Live

- Se incorporó el servicio de seguimiento orbital con mapas, imágenes y vídeos
  grabados de fuentes NASA, música original generada localmente y una
  comprobación previa de FFmpeg y audio.
- El panel del portal permite solicitar explícitamente el inicio público o
  detener la emisión. El token de control no se monta en Homepage ni se guarda
  en el repositorio.
- El arranque automático permanece desactivado; el ejemplo de configuración
  parte de `ISS_LIVE_DRY_RUN=true` y `ISS_LIVE_AUTO_START=false`.
- El contenido se presenta como seguimiento orbital con imágenes recientes,
  no como cámara en directo desde la ISS.

## Adaptador de cámara A9/V720

Se añadió un adaptador local con controles de autenticación, límites de
recursos y un análisis de riesgos del protocolo. El código upstream no declara
una licencia, por lo que el repositorio descarga una versión fijada y verificada
al prepararlo, en lugar de guardar una copia completa. No se debe desplegar
hasta completar la red aislada, el filtrado de tráfico y las pruebas de
captura indicadas en su guía.

## Copias de seguridad

- El script registra los contenedores que están activos, detiene ese conjunto,
  reinicia exactamente los mismos y elimina el archivo parcial al fallar.
- El timeout de `homelab-backup.service` se amplió a 90 minutos porque la copia
  y la verificación SHA-256 pueden superar el límite anterior de 30 minutos.
- El servidor tiene un drop-in equivalente; se documentó y se alineó el valor
  del archivo de unidad versionado.
- Las copias, sus checksums, tokens OAuth, archivos `.env` reales y datos de
  runtime permanecen fuera del repositorio.

## Verificación y seguridad

- Pasaron 18 pruebas del Factory y 19 de ISS Live.
- Se validaron seis archivos YAML, la sintaxis Python y ocho scripts shell.
- Los ejemplos usan marcadores en lugar de credenciales, usuario o IP local.
- La IP privada del parche A9/V720 solo aparece como contexto del valor
  predeterminado de la cámara upstream; no corresponde a la red del HomeLab.

## Resultado

Los dos flujos de AstroLearner quedan documentados como herramientas locales
con revisión humana y controles explícitos. El adaptador A9/V720 queda preparado,
pero no desplegado. La política de backup queda alineada con la duración real
de la operación y conserva una verificación SHA-256 antes de considerar válida
la copia.
