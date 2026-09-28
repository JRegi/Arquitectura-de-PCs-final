"""Estado en memoria compartido entre el controlador y el panel web."""
from datetime import datetime, timezone
from threading import Lock
import math
import time
import uuid


class EstadoSistema:
    def __init__(self, reloj=time.monotonic):
        self._bloqueo = Lock()
        self._reloj = reloj
        self._captura = {"id": None, "estado": "INACTIVA", "uid": None}
        self._limite_captura = 0
        self._puerta_hasta = 0.0
        self._bloqueo_hasta = 0.0
        self._datos = {
            "puerta": "CERRADA",
            "lector_activo": False,
            "tarjeta_detectada": False,
            "uid_actual": None,
            "ultimo_uid": None,
            "ultimo_resultado": "SIN_LECTURAS",
            "ultimo_evento_utc": None,
            "error": None,
            "fallos_consecutivos": 0,
        }

    def actualizar(self, **cambios):
        with self._bloqueo:
            if 'puerta_hasta' in cambios:
                self._puerta_hasta = cambios.pop('puerta_hasta')
            if 'bloqueo_hasta' in cambios:
                self._bloqueo_hasta = cambios.pop('bloqueo_hasta')
            self._datos.update(cambios)

    def registrar_evento(self, uid, resultado):
        self.actualizar(
            ultimo_uid=uid,
            ultimo_resultado=resultado,
            ultimo_evento_utc=datetime.now(timezone.utc).isoformat(),
        )

    def instantanea(self):
        with self._bloqueo:
            self._vencer_captura()
            ahora = self._reloj()
            return {**self._datos, "captura": dict(self._captura),
                    'puerta_restante_s': math.ceil(max(0, self._puerta_hasta-ahora)) if self._datos['puerta']=='ABIERTA' else 0,
                    'bloqueo_restante_s': math.ceil(max(0, self._bloqueo_hasta-ahora))}

    def _vencer_captura(self):
        # Se llama únicamente con el lock adquirido.
        if self._captura['estado'] == 'ESPERANDO' and self._reloj() >= self._limite_captura:
            self._captura['estado'] = 'VENCIDA'

    def iniciar_captura(self):
        with self._bloqueo:
            self._vencer_captura()
            if not self._datos['lector_activo']:
                raise ValueError('El lector todavía no está disponible.')
            if self._captura['estado'] == 'ESPERANDO':
                raise ValueError('Ya hay una lectura en curso. Esperá o cancelala desde la página que la inició.')
            self._captura = {'id': uuid.uuid4().hex, 'estado': 'ESPERANDO', 'uid': None}
            self._limite_captura = self._reloj() + 30
            return dict(self._captura)

    def cancelar_captura(self, identificador):
        with self._bloqueo:
            if identificador != self._captura['id']:
                raise ValueError('Esta solicitud de lectura ya no está activa.')
            if self._captura['estado'] == 'ESPERANDO':
                self._captura['estado'] = 'CANCELADA'
            return dict(self._captura)

    def procesar_captura(self, uid, lectura_valida=True):
        """El único hilo que lee el RC522 entrega aquí un UID completo.

        True indica al controlador que este muestreo pertenece al registro y
        no debe autorizar acceso. No se toman UID del historial ni del navegador.
        """
        with self._bloqueo:
            estaba_esperando = self._captura['estado'] == 'ESPERANDO'
            self._vencer_captura()
            if self._captura['estado'] == 'ESPERANDO' and lectura_valida and uid is not None:
                self._captura.update(estado='LEIDA', uid=uid)
            return estaba_esperando
