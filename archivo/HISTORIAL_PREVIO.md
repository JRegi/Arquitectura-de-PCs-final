# Control de acceso RFID — avance por hitos

Estado: instalado por SSH en `/home/pi/rfid-acceso`, en `pi@192.168.3.216`.
Verificado el 14/09/2026: Raspberry Pi 4 Model B Rev 1.5, Raspbian Bookworm 12,
kernel 6.6.31+rpt-rpi-v8 y Python 3.11.2 (difiere del contexto inicial Trixie).
SPI ya estaba habilitado; dependencias y permisos ya estaban disponibles.
`gpiochip0` corresponde a `pinctrl-bcm2711`. Las 9 pruebas pasan en el Pi y el
diagnóstico del RC522 devuelve VersionReg `0x92`. Se obtuvieron lecturas reales de ambos objetos: tarjeta `B2-B3-40-30` y
llavero `30-83-9E-D3`. El usuario confirmó el orden de presentación y las
pruebas el 14/09/2026: Hito 1 cerrado.

## Estado actual

Hito 2 cerrado por confirmación del usuario el 25/09/2026. El LCD mostró ambas
líneas y conservó el texto después de la última prueba de 60 s sin refresco.
El historial de fallos intermitentes se conserva al final; su causa no se probó.

LCD: PCF8574 0x27, SDA=BCM23 (pin 16), SCL=BCM5 (pin 29), VCC=3,3 V,
GND común, sin divisores. El mapeo habitual del backpack permitió texto correcto.
BCM22 sigue reservado para LED rojo y BCM2/3 para el teclado.

Configuración persistente preparada en `/boot/firmware/config.txt`:

```ini
[all]
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=5,i2c_gpio_delay_us=5
dtoverlay=spi0-1cs
```

`/etc/modules-load.d/rfid-i2c.conf` carga `i2c-dev`. Se guardó copia de config.txt
antes del cambio. Pendiente reinicio y verificación de ambos overlays: el segundo
libera GPIO7, antes ocupado por SPI0 CS1, conservando el RC522 en SPI0 CS0.
Esto habilita el bus al arrancar; no inicia automáticamente el programa del LCD.

Hito 3 preparado, pendiente de identificar terminales del teclado y probarlo.
Ver [guía del Hito 3](HITO_3_TECLADO.md).

## Objetivo y alcance

Imprimir el UID completo de una tarjeta y un llavero con RC522, usando `spidev`
para SPI0 CE0 y `lgpio` para RST. No usa RPi.GPIO ni controla otros periféricos.
Se presenta una tarjeta por vez: las colisiones se informan, no se implementa
resolución de múltiples tarjetas simultáneas.

El UID se transmite en claro y es clonable: es un identificador, no una credencial.
No se considera Crypto1 una protección de acceso. La verificación de PIN, el
bloqueo temporal y la auditoría se implementarán en los hitos correspondientes.
Este script no concede acceso ni escribe sectores de la tarjeta.

## Cableado fijo

Apagar y desconectar la alimentación del Pi antes de cablear.

| RC522 | BCM | Pin físico del Pi |
|---|---|---|
| SDA / SS / CS | 8 (SPI0 CE0) | 24 |
| SCK | 11 | 23 |
| MOSI | 10 | 19 |
| MISO | 9 | 21 |
| RST | 25 | 22 |
| VCC / 3.3V | — | 1 o 17: 3,3 V, nunca 5 V |
| GND | — | 6 o cualquier GND |
| IRQ | — | Sin conectar |

La etiqueta SDA del módulo corresponde a CS en este montaje SPI, no a I2C.

## Instalación en el Pi

Referencia para reinstalación: en este Pi SPI y ambos paquetes ya estaban
disponibles, por lo que no fue necesario reinstalarlos ni reiniciar.

```bash
sudo raspi-config
# Interface Options → SPI → habilitar
sudo apt update
sudo apt install python3-spidev python3-lgpio
```

Reiniciar si raspi-config lo requiere. Después comprobar:

```bash
ls -l /dev/spidev0.0 /dev/gpiochip*
id
python3 -c 'import spidev, lgpio; print("Dependencias disponibles")'
```

Usar Python del sistema (`/usr/bin/python3`) para las dependencias instaladas con
APT. El usuario necesita permiso sobre SPI y GPIO; verificar antes de cambiar
grupos. No ejecutar permanentemente como root para resolver permisos.

La aplicación usa `/dev/gpiochip0` por defecto. Antes de probar, comprobar que su
label corresponde al controlador GPIO BCM2711 del Pi 4B. Si la numeración del
kernel es otra, usar `--gpiochip N`; esto no cambia los pines BCM del cableado.

## Ejecución y verificación

Desde la carpeta donde se copie el proyecto en el Pi:

```bash
/usr/bin/python3 rc522_uid_reader.py --diagnostico
/usr/bin/python3 rc522_uid_reader.py
```

El diagnóstico inicializa el RC522 y lee VersionReg; 0x91 y 0x92 son las versiones
NXP documentadas. 0x00 o 0xFF hacen fallar la inicialización. Otras versiones se
avisan y requieren validación real: no prueban por sí solas que SPI funcione bien.

1. Acercar solo la tarjeta. Anotar el UID hexadecimal y su longitud.
2. Retirarla y acercarla tres veces: comprobar que el UID sea estable.
3. Repetir con el llavero y comprobar que ambos identificadores sean distintos.
4. Mantener un objeto cerca: se imprime aproximadamente una vez por segundo.
5. Retirar ambos: no deben aparecer UID nuevos.
6. Salir con Ctrl+C y ejecutar de nuevo: GPIO y SPI deben estar disponibles.

Ejemplo ilustrativo, no resultado medido: `UID leído: 01-02-03-04 (4 bytes)`.
El Hito 1 se cierra únicamente cuando el usuario confirme ambas lecturas reales.

## Funcionamiento

El lector inicializa SPI en mode 0 a 1 MHz y hace reset por BCM25. Envía WUPA,
valida ATQA, recorre hasta tres niveles de anticolisión y SELECT, verifica BCC y
CRC del SAK, y devuelve exclusivamente los bytes del UID (4, 7 o 10). Termina
con HALT; la próxima WUPA permite volver a leer el mismo objeto.

Se distingue el silencio normal del timer del chip (25 ms) de un fallo de
comunicación. Un límite adicional de 150 ms usa `time.monotonic()`. Los errores
de protocolo se informan como lectura incompleta y provocan un reinicio del campo
RF seguido de reintento; nunca se publica un UID parcial. Los avisos se limitan a
uno cada 2 s. Los fallos de inicialización o del sistema operativo detienen el
programa. Si los avisos persisten, revisar posición y conexiones. La salida de diagnóstico no reemplaza
la prueba de lectura de UID.

## Pruebas sin hardware

```bash
python3 -m unittest discover -s tests -v
```

Nueve pruebas cubren CRC de HALT con un vector conocido, ausencia, UID completos,
BCC y CRC inválidos, retirada durante lectura, timeout normal, colisión y recuperación del bucle sin publicar UID parciales.
Los intercambios simulados no prueban señales eléctricas ni timing real del Pi.

## Fuentes consultadas

- [NXP MFRC522, datasheet Rev. 3.9](https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf): registros, SPI, timer e IRQ.
- [NXP AN10927](https://www.nxp.com/docs/en/application-note/AN10927.pdf): UID y cascade levels.
- [py-spidev](https://github.com/doceme/py-spidev): API de SPI y xfer2.
- [lgpio, fuente Python oficial](https://github.com/joan2937/lg/blob/master/PY_LGPIO/lgpio_extra.py): GPIO, claims y cierre.
- [Raspberry Pi, configuración](https://www.raspberrypi.com/documentation/computers/configuration.html): habilitación de SPI.

### Diagnóstico de estabilidad del Hito 2

El usuario observó retorno a bloques 37 s después de escribir el texto.
Midió 3,3 V entre VCC y GND del backpack. Durante esa prueba se escribió una
sola vez y se mantuvo abierto el descriptor: siete lecturas a intervalos de
10 s (0–60 s) devolvieron 0x01, sin cambios en los bits LOW esperados.
Esto no prueba estabilidad del controlador LCD ni descarta transitorios de
alimentación. No se aplica refresco o reinicialización periódica como solución.
Pendiente identificar referencia del LCD y verificar alimentación especificada.

### Reprueba del 25/09/2026

El usuario volvió a VCC=3,3 V y conexión directa SDA=BCM23/SCL=BCM5.
Se recreó el overlay temporal y se escribió texto una sola vez. El PCF8574
respondió 0x01 a los 0 y 10 s; la siguiente lectura falló con ENXIO (errno 6).
Cinco reintentos posteriores también fallaron. `pinctrl` mostró SDA y SCL en LOW;
el Pi indicó `throttled=0x0`. No se completó la prueba de 120 s.
Pendiente revisar alimentación/contactos y confirmar retirada completa de los
divisores, incluidas sus resistencias a GND. No se considera resuelto el Hito 2.

Después de un nuevo reinicio, el usuario confirmó retirada completa de los
divisores y VCC a 3,3 V. Se recreó el bus temporal en BCM23/5 y se escribió una
sola vez. El usuario confirmó texto visible; siete lecturas del PCF8574 entre
0 y 60 s mantuvieron 0x01 sin errores I2C. Pendiente confirmación visual al
final de la observación y estabilidad prolongada; no se atribuye una causa
definitiva ni se da por solucionado el fallo intermitente.
