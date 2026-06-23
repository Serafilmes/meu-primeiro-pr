"""
Testes da Missão A (Fatia 2) — Busca CONVERSACIONAL (assistente_ia.py).

A Fatia 2 põe um LLM por cima da busca mecânica da Fatia 1. Estes testes provam
a lógica SEM gastar com a API: o motor real (Claude) é substituído por um motor
FALSO injetado, e o modo 'simulado' (LLM em processo) é exercido de verdade.

Cobre:
   1. estado_ia: desligado / simulado / real conforme o ambiente
   2. disponivel() reflete o estado
   3. _termos_simulados descarta o enchimento e mantém o que importa
   4. interpretar_pergunta (simulado) == tradutor simulado
   5. interpretar_pergunta (motor real falso) usa a saída do "LLM"
   6. interpretar_pergunta degrada quando o motor falha
   7. redigir_resposta (simulado) sem resultados / com resultados
   8. redigir_resposta (motor real falso) usa o texto do "LLM"
   9. redigir_resposta degrada para o molde quando o motor falha
  10. montar_vocabulario reúne grupos, listas e profissionais
  11. responder (desligado) devolve estado desligado, sem resultados
  12. responder (simulado) ponta a ponta: acha material e redige
  13. responder (real, motor falso) traduz, busca e redige com o LLM
  14. responder nunca quebra com pergunta vazia
  15. SEGURANÇA: só TEXTO vai ao motor — nenhum caminho de mídia trafega

Roda sem servidor Flask, sem internet e sem chave. Banco em memória (:memory:),
reaproveitando o harness de seed da Fatia 1.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import banco_dados as bd
import assistente_ia as aia
from teste_missao_a_busca import (
    _banco_de_teste, _inserir_profissional, _inserir_formulario,
    _inserir_cartao, _fazer_match, _inserir_arquivo_com_transcricao, _inserir_chip,
)


_VARS_IA = ("GMA_ANTHROPIC_KEY", "ANTHROPIC_API_KEY", "GMA_IA_SIMULADA", "GMA_IA_MODELO")


class _BaseIA(unittest.TestCase):
    """Isola o ambiente de IA: salva, zera (modo 'desligado') e restaura."""

    def setUp(self):
        self._originais = {k: os.environ.get(k) for k in _VARS_IA}
        # Zera tudo deixando a chave presente-mas-vazia para o .env não vazar para
        # dentro do teste (estado inicial = 'desligado').
        for k in _VARS_IA:
            os.environ[k] = ""

    def tearDown(self):
        for k, v in self._originais.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _modo_simulado(self):
        os.environ["GMA_IA_SIMULADA"] = "1"

    def _modo_real(self):
        os.environ["GMA_ANTHROPIC_KEY"] = "sk-teste-falsa"


class TestEstado(_BaseIA):

    def test_desligado(self):
        self.assertEqual(aia.estado_ia(), "desligado")
        self.assertFalse(aia.disponivel())

    def test_simulado(self):
        self._modo_simulado()
        self.assertEqual(aia.estado_ia(), "simulado")
        self.assertTrue(aia.disponivel())

    def test_real_tem_prioridade(self):
        self._modo_real()
        self._modo_simulado()           # mesmo com simulação ligada, a chave manda
        self.assertEqual(aia.estado_ia(), "real")


class TestTradutorSimulado(_BaseIA):

    def test_descarta_enchimento(self):
        termos = aia._termos_simulados(
            "preciso de um vídeo do show do Péricles com a marca Volkswagen")
        self.assertIn("pericles", termos)
        self.assertIn("volkswagen", termos)
        self.assertIn("show", termos)
        self.assertIn("marca", termos)
        # Palavras de ligação foram descartadas
        for enchimento in ("preciso", "de", "um", "do", "com", "video"):
            self.assertNotIn(enchimento, termos)

    def test_interpretar_simulado_igual(self):
        p = "quero algo da Sunset com a Volkswagen"
        self.assertEqual(
            aia.interpretar_pergunta(p, "", motor=None),
            aia._termos_simulados(p),
        )


class TestTradutorMotor(_BaseIA):

    def test_usa_saida_do_motor(self):
        def motor(system, prompt):
            return "sunset volkswagen", None
        termos = aia.interpretar_pergunta("qualquer coisa", "cardápio", motor=motor)
        self.assertEqual(termos, ["sunset", "volkswagen"])

    def test_degrada_quando_motor_falha(self):
        def motor(system, prompt):
            return None, "sem internet"
        # Cai no extrator da própria pergunta (sem o enchimento)
        termos = aia.interpretar_pergunta("o show do Péricles", "", motor=motor)
        self.assertIn("pericles", termos)
        self.assertIn("show", termos)


class TestRedator(_BaseIA):

    def test_simulado_sem_resultados(self):
        txt = aia.redigir_resposta("nada", [], motor=None)
        self.assertIn("Não encontrei", txt)
        self.assertIn("simulado", txt)

    def test_simulado_com_resultados(self):
        resultados = [{"prof_nome": "ANA LIMA", "numero_cartao": "ANA_001",
                       "campos_bateram": ["Profissional"], "arquivos_transcritos": []}]
        txt = aia.redigir_resposta("ana", resultados, motor=None)
        self.assertIn("ANA_001", txt)
        self.assertIn("1 material", txt)

    def test_motor_real_usa_texto(self):
        def motor(system, prompt):
            return "Use o cartão ANA_001.", None
        txt = aia.redigir_resposta("ana", [{"prof_nome": "ANA", "numero_cartao": "ANA_001",
                                            "campos_bateram": [], "arquivos_transcritos": []}],
                                   motor=motor)
        self.assertEqual(txt, "Use o cartão ANA_001.")

    def test_motor_falha_cai_no_molde(self):
        def motor(system, prompt):
            return None, "timeout"
        txt = aia.redigir_resposta("x", [], motor=motor)
        self.assertIn("Não encontrei", txt)


class TestVocabulario(_BaseIA):

    def test_reune_tudo(self):
        conn, _ = _banco_de_teste()
        try:
            _inserir_profissional(conn, "ANA LIMA")
            conn.execute("INSERT INTO grupos_classificacao (chave, rotulo, ativo) "
                         "VALUES ('marca', 'Marca', 1)")
            conn.execute("INSERT INTO listas_contexto (tipo, valor, ativo) "
                         "VALUES ('marca', 'Volkswagen', 1)")
            conn.commit()
            vocab = aia.montar_vocabulario(conn)
            self.assertIn("ANA LIMA", vocab)
            self.assertIn("Marca", vocab)
            self.assertIn("Volkswagen", vocab)
        finally:
            conn.close()


class TestResponder(_BaseIA):

    def _semear(self, conn):
        """Um cartão casado com áudio transcrito mencionando 'Péricles'."""
        _inserir_profissional(conn, "ANA LIMA")
        fid = _inserir_formulario(conn, "ANA LIMA", "AUDIO")
        cid = _inserir_cartao(conn, "ANA_001", "AUDIO")
        _fazer_match(conn, cid, fid)
        _inserir_arquivo_com_transcricao(conn, cid, "audio01.wav",
                                         "Péricles cantou no palco principal")
        _inserir_chip(conn, fid, "marca", "Volkswagen")
        return cid, fid

    def test_desligado_nao_busca(self):
        conn, _ = _banco_de_teste()
        try:
            self._semear(conn)
            r = aia.responder(conn, "pericles")
            self.assertEqual(r["estado"], "desligado")
            self.assertEqual(r["resultados"], [])
            self.assertIsNone(r["resposta"])
        finally:
            conn.close()

    def test_simulado_ponta_a_ponta(self):
        self._modo_simulado()
        conn, _ = _banco_de_teste()
        try:
            self._semear(conn)
            r = aia.responder(conn, "quero o take do Péricles")
            self.assertEqual(r["estado"], "simulado")
            self.assertIn("pericles", r["termos"])
            self.assertTrue(r["resultados"], "deveria achar o cartão do Péricles")
            self.assertIn("ANA_001", r["resposta"])
        finally:
            conn.close()

    def test_real_com_motor_falso(self):
        self._modo_real()
        chamadas = []

        def motor(system, prompt):
            chamadas.append((system, prompt))
            if system == aia._SYSTEM_TRADUTOR:
                return "pericles", None
            return "O cartão ANA_001 tem o áudio com o Péricles.", None

        conn, _ = _banco_de_teste()
        try:
            self._semear(conn)
            r = aia.responder(conn, "onde o Péricles aparece?", motor=motor)
            self.assertEqual(r["estado"], "real")
            self.assertEqual(r["termos"], ["pericles"])
            self.assertTrue(r["resultados"])
            self.assertEqual(r["resposta"], "O cartão ANA_001 tem o áudio com o Péricles.")
            self.assertEqual(len(chamadas), 2, "deve traduzir e redigir (2 chamadas)")
        finally:
            conn.close()

    def test_pergunta_vazia_nao_quebra(self):
        self._modo_simulado()
        conn, _ = _banco_de_teste()
        try:
            r = aia.responder(conn, "   ")
            self.assertEqual(r["resultados"], [])
            self.assertIsNone(r["resposta"])
        finally:
            conn.close()


class TestSegurancaMidia(_BaseIA):
    """A mídia NUNCA sobe: só texto (transcrição/classificação) vai ao motor."""

    def test_motor_nao_recebe_caminho_de_midia(self):
        self._modo_real()
        prompts = []

        def motor(system, prompt):
            prompts.append(prompt)
            if system == aia._SYSTEM_TRADUTOR:
                return "pericles", None
            return "resposta", None

        conn, _ = _banco_de_teste()
        try:
            # O seed usa caminhos /Volumes/AUDIO/... — não podem vazar para a API.
            _inserir_profissional(conn, "ANA LIMA")
            fid = _inserir_formulario(conn, "ANA LIMA", "AUDIO")
            cid = _inserir_cartao(conn, "ANA_001", "AUDIO")
            _fazer_match(conn, cid, fid)
            _inserir_arquivo_com_transcricao(conn, cid, "audio01.wav", "Péricles cantou")
            aia.responder(conn, "pericles", motor=motor)
            self.assertTrue(prompts, "o motor deveria ter sido chamado")
            for p in prompts:
                self.assertNotIn("/Volumes/", p, "caminho de mídia vazou para a API!")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
