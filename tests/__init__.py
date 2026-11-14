"""Os testes NUNCA usam o banco real: todo o pacote roda numa pasta temporária.

Isto roda antes de qualquer módulo de teste importar o servidor, seja qual for a ordem.
"""
import os
import tempfile

os.environ["ARTEMIS_DATA_DIR"] = tempfile.mkdtemp(prefix="artemis_test_")
