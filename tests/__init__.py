"""Os testes NUNCA usam o banco real: todo o pacote roda numa pasta temporária.

Isto roda antes de qualquer módulo de teste importar o servidor, seja qual for a ordem.
"""
import os
import tempfile
from pathlib import Path

os.environ["ARTEMIS_DATA_DIR"] = tempfile.mkdtemp(prefix="artemis_test_")

# Dados que o servidor carrega ao subir (lugares de hunt, tabela da TibiaWiki, meta). Não são estado de teste.
_DADOS_DE_INICIO = {"hunt_places", "wiki_items", "wiki_item_buyers", "wiki_npcs", "wiki_images", "meta",
                    "translations"}


def limpar_banco(conn) -> None:
    """Apaga o estado deixado por outros testes, para que contagens e listas não dependam da ordem da suíte."""
    arquivo = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    if Path(tempfile.gettempdir()).resolve() not in arquivo.parents:
        raise RuntimeError(f"Os testes não apagam banco fora da pasta temporária: {arquivo}")
    tabelas = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for t in tabelas:
        if t.startswith("sqlite_") or t in _DADOS_DE_INICIO:
            continue
        conn.execute(f'DELETE FROM "{t}"')
    conn.commit()
