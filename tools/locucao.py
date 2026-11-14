"""Gera a locução do vídeo do 4rt3mi5 com o edge-tts (vozes neurais grátis, sem chave).

Saída em video/locucao/ (fora do Git):
  amostras/*.mp3      a mesma frase em cada voz, para comparar
  cenas/NN-*.mp3/.srt uma faixa + legenda por cena do roteiro (para encaixar no Remotion)
  locucao-completa.mp3 todas as cenas em sequência

Uso: .venv\\Scripts\\python tools/locucao.py            (requer: pip install edge-tts)
     .venv\\Scripts\\python tools/locucao.py --voz pt-BR-AntonioNeural --velocidade -8% --tom -4Hz
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import edge_tts

OUT = Path(__file__).resolve().parent.parent / "video" / "locucao"

ROTEIRO = [
    ("abertura", "Toda hunt conta uma história. Mas quem guarda ela?"),
    ("lootsplit", "Copiou o analyser? Um Control V... e o loot está dividido, com o comando de transferência pronto."),
    ("ranking-pt", "E fica tudo guardado. Veja quem segurou a linha de frente, quem curou a PT, e quem trouxe o loot. Hunt após hunt."),
    ("stacker", "Sozinho também: cada sessão vira histórico, XP por hora e lucro de verdade. Semana a semana."),
    ("itens", "Saiba o que mais dropou e o que mais vale. Item sem NPC? Você coloca o seu preço."),
    ("aviso-venda", "Defina uma quantidade, e o Ártemis avisa a hora de vender."),
    ("hunts", "Compare hunts pelos dados reais de quem caça nelas. No seu level."),
    ("conquistas", "Bata recordes, desbloqueie conquistas... e a cada trinta dias seguidos, ganhe dias extras de acesso."),
    ("final", "Ártemis. Sua hunt, guardada. Peça seu código e comece hoje."),
]
# Na fala, "4rt3mi5" vira "Ártemis" (senão o narrador lê letra por letra); na tela continua 4rt3mi5.

AMOSTRA = "Toda hunt conta uma história. Mas quem guarda ela? Ártemis: sua hunt, guardada."
VOZES = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural",
         "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural"]


async def falar(texto: str, voz: str, mp3: Path, rate: str, pitch: str, srt: Path | None = None) -> None:
    """O serviço às vezes recusa pedidos seguidos: tenta de novo com pausa crescente."""
    for tentativa in range(5):
        try:
            return await _falar(texto, voz, mp3, rate, pitch, srt)
        except edge_tts.exceptions.NoAudioReceived:
            if tentativa == 4:
                raise
            await asyncio.sleep(2 + tentativa * 3)


async def _falar(texto: str, voz: str, mp3: Path, rate: str, pitch: str, srt: Path | None = None) -> None:
    com = edge_tts.Communicate(texto, voz, rate=rate, pitch=pitch, boundary="SentenceBoundary")
    sub = edge_tts.SubMaker()
    with mp3.open("wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                sub.feed(chunk)
    if srt:
        srt.write_text(sub.get_srt(), encoding="utf-8")


async def main(voz: str, rate: str, pitch: str) -> None:
    (OUT / "amostras").mkdir(parents=True, exist_ok=True)
    (OUT / "cenas").mkdir(parents=True, exist_ok=True)
    for v in VOZES:
        await falar(AMOSTRA, v, OUT / "amostras" / f"{v}.mp3", rate, pitch)
        print("amostra:", v)
    partes = []
    for i, (nome, texto) in enumerate(ROTEIRO, 1):
        mp3 = OUT / "cenas" / f"{i:02d}-{nome}.mp3"
        await falar(texto, voz, mp3, rate, pitch, mp3.with_suffix(".srt"))
        partes.append(mp3.read_bytes())
        print("cena:", mp3.name)
    (OUT / "locucao-completa.mp3").write_bytes(b"".join(partes))  # MP3 aceita concatenar quadros
    print("pronto:", OUT)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--voz", default="pt-BR-AntonioNeural")
    p.add_argument("--velocidade", default="-8%")
    p.add_argument("--tom", default="-4Hz")
    a = p.parse_args()
    asyncio.run(main(a.voz, a.velocidade, a.tom))
