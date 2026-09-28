"""Lógica de los modos de acceso y combinación RFID.

El UID es clonable. Esta demo no autentica criptográficamente la tarjeta.
El controlador no depende de GPIO, lo que permite probarlo sin hardware.
"""
import logging
import math
import time


class ControladorAcceso:
    def __init__(self, servo, pantalla, esta_autorizado, obtener_modo,
                 estado_sistema=None, tiempo_abierto_s=5,
                 tiempo_retiro_tarjeta_s=1, reloj=time.monotonic,
                 secuencias=None, esta_registrado=None, obtener_tiempo_abierto=None):
        self.servo = servo
        self.pantalla = pantalla
        self.esta_autorizado = esta_autorizado
        self.obtener_modo = obtener_modo
        self.modo = obtener_modo()
        self.estado_sistema = estado_sistema
        self.tiempo_abierto_s = tiempo_abierto_s
        self.obtener_tiempo_abierto = obtener_tiempo_abierto or (lambda: self.tiempo_abierto_s)
        self.tiempo_retiro_tarjeta_s = tiempo_retiro_tarjeta_s
        self.reloj = reloj
        self.secuencias = secuencias
        self.esta_registrado = esta_registrado or esta_autorizado
        self.estado = 'REPOSO'
        self.vencimiento = 0.0
        self.esperando_retiro = False
        self.sin_tarjeta_desde = None
        self.ultimo_texto = None
        self.fallos_consecutivos = 0
        self.bloqueado_hasta = 0.0
        self.secuencia_activa = None
        self.siguiente_paso = 0
        self.plazo_secuencia = 0.0
        self.palabra_actual = 'Acceso permitido'
        self._mostrar('Control acceso', 'Acerque tarjeta')
        self._estado_web(puerta='CERRADA')

    def _estado_web(self, **cambios):
        if self.estado_sistema is not None:
            self.estado_sistema.actualizar(**cambios)

    def _evento_web(self, uid, resultado):
        if self.estado_sistema is not None:
            self.estado_sistema.registrar_evento(uid, resultado)

    def _mostrar(self, primera, segunda):
        texto = (primera, segunda)
        if texto != self.ultimo_texto:
            self.pantalla.mostrar_lineas(*texto)
            self.ultimo_texto = texto

    def lectura_invalida(self):
        # Una falla RF nunca cuenta como retirada confirmada ni como autorización.
        self.sin_tarjeta_desde = None

    def _mostrar_cuenta(self, ahora):
        if self.estado == 'ABIERTO':
            self._mostrar(self.palabra_actual, f'Cierra en {math.ceil(max(0, self.vencimiento-ahora))} s')
        elif self.estado == 'BLOQUEADO':
            self._mostrar('Bloqueado', f'Espera {math.ceil(max(0, self.bloqueado_hasta-ahora))} s')

    def _limpiar_secuencia(self):
        self.secuencia_activa = None
        self.siguiente_paso = 0
        self.plazo_secuencia = 0.0

    def _abrir(self, uid, palabra, resultado):
        self.servo.abrir()
        self.estado = 'ABIERTO'
        self.vencimiento = self.reloj() + self.obtener_tiempo_abierto()
        self.palabra_actual = palabra
        self._estado_web(puerta='ABIERTA', puerta_hasta=self.vencimiento)
        self._evento_web(uid, resultado)
        self._mostrar_cuenta(self.reloj())

    def _paso_combinacion(self, uid, ahora):
        # Un cambio del padrón invalida la combinación que estaba en curso.
        if self.secuencia_activa is not None:
            actual = self.secuencias.secuencia_iniciada_por(self.secuencia_activa['pasos'][0]['uid'])
            if actual != self.secuencia_activa or ahora >= self.plazo_secuencia:
                self._limpiar_secuencia()
        if self.secuencia_activa is not None:
            if self.secuencia_activa['pasos'][self.siguiente_paso]['uid'] == uid:
                self.siguiente_paso += 1
                if self.siguiente_paso == len(self.secuencia_activa['pasos']):
                    palabra = self.secuencia_activa['palabra_final']
                    self._limpiar_secuencia()
                    self._abrir(uid, palabra, 'SECUENCIA_COMPLETADA')
                else:
                    self.plazo_secuencia = self.reloj() + self.obtener_tiempo_abierto()
                return
            self._limpiar_secuencia()
        secuencia = self.secuencias.secuencia_iniciada_por(uid) if self.secuencias else None
        if secuencia and all(paso['habilitada'] for paso in secuencia['pasos']):
            self.secuencia_activa = secuencia
            self.siguiente_paso = 1
            self.plazo_secuencia = self.reloj() + self.obtener_tiempo_abierto()

    def actualizar(self, uid, lectura_valida=True):
        ahora = self.reloj()
        modo = self.obtener_modo()
        if modo != self.modo:
            self.modo = modo
            self._limpiar_secuencia()
            if self.estado == 'ABIERTO':
                self.servo.cerrar()
                self._estado_web(puerta='CERRADA', puerta_hasta=0)
            if self.estado != 'BLOQUEADO':
                self.estado = 'REPOSO'
            self.esperando_retiro = True
            self.sin_tarjeta_desde = None
            self._mostrar('Control acceso', 'Retire tarjeta')
            return
        # El cierre tiene prioridad sobre nuevas lecturas y sobre escrituras LCD.
        if self.estado == 'ABIERTO' and ahora >= self.vencimiento:
            self.servo.cerrar()
            self.estado = 'REPOSO'
            self._estado_web(puerta='CERRADA', puerta_hasta=0)
            self._limpiar_secuencia()
            logging.info('Servo en posición cerrada')
            self._mostrar('Control acceso', 'Retire tarjeta' if self.esperando_retiro else 'Acerque tarjeta')
        elif self.estado == 'DENEGADO' and ahora >= self.vencimiento:
            self.estado = 'REPOSO'
            self._mostrar('Control acceso', 'Retire tarjeta' if self.esperando_retiro else 'Acerque tarjeta')

        if self.estado == 'BLOQUEADO' and ahora >= self.bloqueado_hasta:
            self.estado = 'REPOSO'
            self.fallos_consecutivos = 0
            self._estado_web(bloqueo_hasta=0, fallos_consecutivos=0)
            self._mostrar('Control acceso', 'Acerque tarjeta')

        if self.secuencia_activa is not None and ahora >= self.plazo_secuencia:
            self._limpiar_secuencia()

        if self.estado_sistema is not None and self.estado_sistema.procesar_captura(uid, lectura_valida):
            # Mantener el cierre por tiempo (arriba), pero impedir que la lectura
            # de alta abra. Tras capturar/cancelar se exige retirar la tarjeta.
            self.esperando_retiro = True
            self.sin_tarjeta_desde = None
            self._limpiar_secuencia()
            if lectura_valida:
                self._estado_web(tarjeta_detectada=uid is not None, uid_actual=uid)
            if self.estado == 'REPOSO':
                self._mostrar('Alta de tarjeta', 'Acerque tarjeta' if uid is None else 'UID leido')
            else:
                self._mostrar_cuenta(ahora)
            return

        if not lectura_valida:
            self.lectura_invalida()
            self._mostrar_cuenta(ahora)
            return
        if uid is None:
            self._estado_web(tarjeta_detectada=False, uid_actual=None)
            if self.sin_tarjeta_desde is None:
                self.sin_tarjeta_desde = ahora
            if ahora - self.sin_tarjeta_desde >= self.tiempo_retiro_tarjeta_s:
                self.esperando_retiro = False
                if self.estado == 'REPOSO':
                    self._mostrar('Control acceso', 'Acerque tarjeta')
            self._mostrar_cuenta(ahora)
            return
        self._estado_web(tarjeta_detectada=True, uid_actual=uid)
        self.sin_tarjeta_desde = None
        if self.esperando_retiro or self.estado in ('ABIERTO', 'DENEGADO', 'BLOQUEADO'):
            # No prolongar apertura ni repetir ciclos con una tarjeta sostenida.
            self.esperando_retiro = True
            self._mostrar_cuenta(ahora)
            return
        self.esperando_retiro = True
        if not self.esta_autorizado(uid):
            self.estado = 'DENEGADO'
            self.vencimiento = ahora + 2
            self._limpiar_secuencia()
            logging.info('UID no autorizado: %s', uid)
            if not self.esta_registrado(uid):
                self.fallos_consecutivos += 1
                self._estado_web(fallos_consecutivos=self.fallos_consecutivos)
            if self.fallos_consecutivos >= 3:
                self.estado = 'BLOQUEADO'
                self.bloqueado_hasta = self.reloj() + 10
                self._estado_web(bloqueo_hasta=self.bloqueado_hasta)
                self._evento_web(uid, 'BLOQUEO_10_SEGUNDOS')
                self._mostrar_cuenta(self.reloj())
            else:
                self._evento_web(uid, 'RFID_INCORRECTO')
                self._mostrar('Acceso', 'incompleto')
            return
        self.fallos_consecutivos = 0
        self._estado_web(fallos_consecutivos=0)
        logging.info('UID autorizado: %s', uid)
        if self.modo == 'ACCESO':
            self._abrir(uid, 'Acceso permitido', 'ACCESO_CONCEDIDO')
        else:
            self._paso_combinacion(uid, ahora)
