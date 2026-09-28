import unittest
from unittest.mock import Mock, patch, MagicMock
from rc522_uid_reader import LectorMFRC522, ErrorLectura, calcular_crc_a, principal


class PruebasProtocolo(unittest.TestCase):
    def test_reintenta_error_sin_publicar_uid_parcial(self):
        lector = MagicMock()
        lector.__enter__.return_value = lector
        lector.version = 0x92
        lector.leer_uid.side_effect = [ErrorLectura('BCC incorrecto'),
                                      [1, 2, 3, 4], KeyboardInterrupt()]
        with patch('rc522_uid_reader.LectorMFRC522', return_value=lector), \
             patch('sys.argv', ['rc522_uid_reader.py']), \
             patch('rc522_uid_reader.signal.signal'), \
             patch('rc522_uid_reader.time.sleep'), patch('builtins.print') as imprimir:
            self.assertEqual(principal(), 0)
        lector.restablecer_campo.assert_called_once()
        lector.__exit__.assert_called_once()
        lecturas = [llamada.args[0] for llamada in imprimir.call_args_list
                    if llamada.args and str(llamada.args[0]).startswith('UID leído:')]
        self.assertEqual(lecturas, ['UID leído: 01-02-03-04 (4 bytes)'])

    def test_crc_halt_vector_conocido(self):
        self.assertEqual(calcular_crc_a([0x50, 0x00]), [0x57, 0xCD])

    def crear_lector(self, respuestas):
        lector = LectorMFRC522.__new__(LectorMFRC522)
        lector._transceive = Mock(side_effect=respuestas)
        return lector

    def test_ausencia_normal(self):
        self.assertIsNone(self.crear_lector([None]).leer_uid())

    def test_uid_completo_y_sin_bcc_ni_cascade_tag(self):
        for uid in ([1, 2, 3, 4], [4, 1, 2, 3, 4, 5, 6],
                    [4, 1, 2, 3, 4, 5, 6, 7, 8, 9]):
            with self.subTest(longitud=len(uid)):
                respuestas = [([0x04, 0], 16)]
                restante = list(uid)
                while restante:
                    continua = len(restante) > 4
                    bloque = [0x88] + restante[:3] if continua else restante[:4]
                    restante = restante[3:] if continua else []
                    bcc = bloque[0] ^ bloque[1] ^ bloque[2] ^ bloque[3]
                    sak = [0x04 if continua else 0x08]
                    respuestas.extend([(bloque + [bcc], 40),
                                       (sak + calcular_crc_a(sak), 24)])
                respuestas.append(None)  # HALT
                lector = self.crear_lector(respuestas)
                self.assertEqual(lector.leer_uid(), uid)
                self.assertEqual(lector._transceive.call_args.args[0],
                                 [0x50, 0, 0x57, 0xCD])

    def test_rechaza_bcc_corrupto(self):
        lector = self.crear_lector([([4, 0], 16), ([1, 2, 3, 4, 0], 40)])
        with self.assertRaisesRegex(ErrorLectura, 'BCC'):
            lector.leer_uid()

    def test_rechaza_crc_sak_corrupto(self):
        lector = self.crear_lector([([4, 0], 16), ([1, 2, 3, 4, 4], 40),
                                   ([8, 0, 0], 24)])
        with self.assertRaisesRegex(ErrorLectura, 'CRC'):
            lector.leer_uid()

    def test_no_confunde_tarjeta_retirada_con_uid(self):
        lector = self.crear_lector([([4, 0], 16), None])
        with self.assertRaises(ErrorLectura):
            lector.leer_uid()

    def test_timer_chip_es_ausencia_y_limpia_comando(self):
        lector = LectorMFRC522.__new__(LectorMFRC522)
        lector._escribir_registro = Mock()
        lector._leer_registro = Mock(side_effect=[1, 0])
        self.assertIsNone(lector._transceive([0x52], 7))
        self.assertEqual(lector._escribir_registro.call_args.args, (1, 0))
        lector._escribir_registro.assert_any_call(4, 0x7F)

    def test_colision_es_error(self):
        lector = LectorMFRC522.__new__(LectorMFRC522)
        lector._escribir_registro = Mock()
        lector._leer_registro = Mock(side_effect=[0x22, 0x08])
        with self.assertRaises(ErrorLectura):
            lector._transceive([0x52], 7)


if __name__ == '__main__':
    unittest.main()
