# Copilot RH Recrutement

Plateforme RH en Python (FastAPI) qui s'appuie sur un LLM pour :

1. **Analyser des CVs** : extraction en JSON validé par Pydantic (score de 0 à 100, compétences, justifications, points de vigilance)
2. **Répondre aux questions RH** : assistant RAG qui répond uniquement à partir des politiques RH indexées
3. **Qualifier les candidats** : agent qui recherche et réserve des créneaux d'entretien (tool calling)
4. **Discuter en streaming** : chat en SSE, mot à mot

Le projet avance par étapes (voir [docs/plan_de_developpement.md](docs/plan_de_developpement.md)), donc certaines fonctionnalités ne sont pas encore disponibles.

## Prérequis

- Python 3.11 ou plus récent
- Une clé API Gemini gratuite, à créer sur [Google AI Studio](https://aistudio.google.com)

## Installation

```powershell
# Windows PowerShell, depuis la racine du projet
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Sous Linux ou macOS, activez le venv avec `source venv/bin/activate`.

## Configuration

Copiez le modèle de configuration, puis remplissez-le :

```powershell
copy .env.example .env
```

| Variable | Rôle |
| --- | --- |
| `LLM_PROVIDER` | Fournisseur du LLM (`gemini`) |
| `LLM_MODEL` | Nom exact du modèle, à choisir dans Google AI Studio (une variante « Flash » est recommandée) |
| `LLM_API_KEY` | Votre clé API |
| `EMBEDDING_MODEL` | Modèle d'embedding local du RAG (`all-MiniLM-L6-v2` par défaut) |
| `CHROMA_PATH` | Dossier de la base vectorielle |
| `LOG_LEVEL` | Niveau des logs (`INFO` par défaut) |
| `CORS_ORIGINS` | Origines du frontend autorisées, au format JSON |

Le fichier `.env` contient votre clé : il est ignoré par Git, ne le committez jamais.

## Lancement

1. Vérifiez que le LLM répond :

   ```powershell
   python -m scripts.check_llm
   ```

2. Démarrez l'API :

   ```powershell
   uvicorn app.main:create_app --factory --reload
   ```

3. Ouvrez la documentation interactive : <http://localhost:8000/docs>

Au premier lancement, le modèle d'embedding (environ 80 Mo) est téléchargé, ce qui ralentit le démarrage.

### Endpoints disponibles

| Méthode | Route | Rôle |
| --- | --- | --- |
| `GET` | `/health` | Vérifie que l'API tourne |
| `POST` | `/api/candidates/parse` | Analyse un CV au format PDF |
| `POST` | `/api/rag/ask` | Pose une question sur les politiques RH |

## Tests

```powershell
pytest            # tests rapides, sans réseau (faux LLM)
pytest -m llm     # tests officiels avec le vrai LLM (consomme du quota)
```

## Structure

```
app/
  api/        # routes FastAPI
  llm/        # couche d'abstraction LLM (un adaptateur par fournisseur)
  data/       # données du cahier des charges
  models/     # schémas Pydantic
  services/   # logique métier
scripts/      # outils en ligne de commande (check_llm)
tests/        # tests pytest
docs/         # cahier des charges et plan de développement
```
