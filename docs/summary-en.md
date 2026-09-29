# HomeLab project summary

## Overview

This project transforms a repurposed laptop into a secure, observable, and
recoverable home server. Its purpose is not only to host services, but also to
provide a practical environment for learning Linux administration, networking,
cybersecurity, containers, observability, electronics, and automation.

The platform currently combines a central Ubuntu Server with an environmental
sensor node based on an ESP8266. All administrative interfaces remain private
and are accessed through the local network or an authorized Tailscale device.

## Infrastructure

- Ubuntu Server 24.04 LTS on repurposed hardware.
- Docker Compose for isolated and reproducible services.
- Caddy as the single HTTPS entry point for internal web applications.
- AdGuard Home for local DNS, filtering, and `*.home.arpa` name resolution.
- Tailscale for encrypted remote access without exposing services publicly.
- SSH restricted to public-key authentication.
- UFW firewall rules limited to the required traffic.

## Monitoring and operations

- Prometheus stores system, service, and environmental time-series data.
- Node Exporter exposes operating-system metrics.
- Grafana provides dashboards for health, performance, backups, alerts, and
  environmental measurements.
- Uptime Kuma monitors service availability and latency.
- NetAlertX provides local network inventory and event visibility.
- Homepage acts as a private central portal for operational information.
- Systemd services generate sanitized summaries without exposing logs,
  credentials, device identifiers, or private operational details to Homepage.

## Environmental sensor prototype

The first physical monitoring node uses a WeMos D1 mini-compatible ESP8266 and
a DHT11 temperature and humidity sensor. ESPHome manages the firmware, exposes
Prometheus metrics, and supports password-protected over-the-air updates.

```text
DHT11 -> ESP8266 / ESPHome -> Prometheus -> Grafana
                                      `-> sanitized JSON -> Homepage
```

The prototype currently supports:

- Temperature and humidity sampling every five seconds.
- Live readings through the ESPHome interface and Homepage.
- Historical analysis through Prometheus and Grafana.
- Availability monitoring with the Prometheus `up` metric.
- OTA firmware updates after the initial USB installation.
- A reserved DHCP address for stable collection.

The DHT11 is suitable for validating the complete pipeline, although its
accuracy is limited and its readings can be affected by heat from the ESP8266.
A future revision will use a more accurate sensor and a ventilated enclosure.

## Backup and recovery

- Consistent daily backups stored on the server.
- SHA-256 integrity verification.
- Automated retention.
- A second encrypted weekly copy stored on another device.
- Practical restoration testing to verify that backups are usable.

## Security principles

The project follows a simple rule: expose only what is necessary.

- Internal services listen on loopback whenever possible.
- Caddy is the only HTTPS entry point on the LAN.
- Remote access uses a private encrypted network.
- Credentials, Wi-Fi secrets, OTA passwords, private IP addresses, MAC
  addresses, serial numbers, tokens, and private keys are excluded from Git.
- Public configuration files use placeholders such as `<SERVER_IP>` and
  `<SENSOR_IP>`.
- Homepage receives only explicitly sanitized data and has no Docker socket or
  direct access to private system logs.

## Current outcome and next steps

The project now provides an end-to-end path from physical sensing to collection,
storage, visualization, and operational presentation. It has also served as a
practical troubleshooting exercise across hardware assembly, serial
communication, Wi-Fi connectivity, DHCP, OTA authentication, container mounts,
and time-series monitoring.

Planned improvements include additional sensor nodes, air-quality measurements,
better enclosures, offline alerts, recovery automation, and anomaly detection
once enough reliable historical data has been collected.
