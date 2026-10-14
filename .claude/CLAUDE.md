# CLAUDE.md — Plateforme SaaS RH & Assistant Copilot de Recrutement

## Le projet

Application RH en Python avec 4 piliers LLM :
1. **Parsing de CV** → JSON strict validé par Pydantic (score 0-100, compétences, justifications, points de vigilance)
2. **Assistant RH RAG** → répond uniquement à partir des politiques RH indexées
3. **Agent de qualification** → tool calling (recherche et réservation de créneaux, statut candidat)
4. **Chat en streaming SSE** → texte mot à mot + événements d'outils

Documents de référence :
- `docs/cahier_des_charges.md` : fait foi en cas de doute (données, endpoints, tests officiels)
- `docs/plan_de_developpement.md` : les étapes dans l'ordre, avec leurs critères de fin

## Comment travailler avec moi

- **Tu codes, je relis.** Écris le code, je fais la revue avant de valider.
- Travaille une étape du plan à la fois, en petits changements faciles à relire. Ne passe pas à l'étape suivante sans mon accord.
- Avant de commencer, annonce le plan en quelques lignes et attends mon accord.
- Après chaque modification, lance `pytest` et corrige ce qui casse.
- À la fin, résume pour ma revue : fichiers modifiés, choix faits et pourquoi, points à vérifier en priorité.
- Quand tu repères une erreur ou une meilleure approche, dis-le, même si je n'ai rien demandé.
- Réponds en français. Code et noms (variables, fonctions, classes, fichiers) en anglais uniquement ; commentaires, docstrings et fichiers Markdown en français.
  Les noms venant du cahier des charges sont traduits en anglais, avec le nom français d'origine en commentaire juste au-dessus (ex. `# POLITIQUES_RH` au-dessus de `HR_POLICIES`). Seul le nom change : le contenu des données reste identique.
  Cela vaut aussi pour les outils de la section 6 : `rechercher_creneaux_entretien` → `search_interview_slots`, `reserver_entretien` → `book_interview` (paramètres traduits aussi). Leurs docstrings et leurs valeurs de retour restent identiques au cahier des charges.

## Stack

- Python 3.11+ dans un venv (`venv/`)
- FastAPI + uvicorn, Pydantic, pydantic-settings, python-multipart
- LLM : fournisseur et modèle interchangeables. Ils sont lus depuis `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`) via la config centralisée, jamais codés en dur. Fournisseur de départ : **Gemini** (SDK `google-genai`, clé gratuite via Google AI Studio). Le reste du code passe par une couche d'abstraction (un adaptateur par fournisseur) et n'importe jamais directement un SDK de fournisseur.
- Embeddings : fonction d'embedding par défaut de ChromaDB (`all-MiniLM-L6-v2`, locale, sans clé ni coût). Le modèle est lu depuis `.env` (`EMBEDDING_MODEL`) ; si le test officiel RAG échoue sur le français, passer à `paraphrase-multilingual-MiniLM-L12-v2`.
- Base vectorielle : ChromaDB
- PDF : pdfplumber
- SSE : natif FastAPI (`fastapi.sse.EventSourceResponse`, sans dépendance en plus)
- Tests : pytest + httpx2 (pour le `TestClient`)

## Règles de code

- Code simple et lisible, sans dépendance superflue.
- Ne pas ajouter de bibliothèque (UI, Markdown, état, etc.) sans demande explicite.
- Respecter les bonnes pratiques python
- En cas de dépréciation (avertissement, doc, changelog), passer directement à l'alternative recommandée, même si cela ajoute ou remplace une dépendance.

## Workflow Git

- La branche `main` est protégée : ne jamais pousser directement dessus.
- Pour toute modification : créer une branche (`git checkout -b <nom-court>`), committer, pousser la branche, puis ouvrir une pull request.
- Messages de commit courts, à l'impératif, en français (ex. : « Ajoute la section compétences »).
- Un commit = un changement cohérent.
- Ne jamais utiliser `git push --force`, `git reset --hard` ni supprimer de branche distante.
- une branche = une feature
- Demander confirmation avant chaque commit et chaque push.
- Ne jamais committer de secrets, de clés API ou de données personnelles non destinées à être publiques (adresse postale complète, numéro de téléphone, etc.) sans validation.

## Commandes

```bash
# Windows PowerShell
venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload    # interface → http://localhost:8000/ ; API → /docs
python -m scripts.check_llm      # vérifie l'appel réel au LLM
pytest                           # tests rapides, sans réseau (faux LLM)
pytest -m llm                    # tests officiels avec le vrai LLM (consomme du quota)
python -m scripts.evaluate       # rapport des critères d'évaluation pour le README (≈ 25 appels)
```

## Architecture

Architecture en couches (routes → services → infrastructure), avec ports et adaptateurs pour le LLM.

- Les routes (`app/api/`) ne contiennent aucune logique métier : elles valident l'entrée, appellent un service et renvoient la réponse.
- Les services (`app/services/`) ne dépendent pas de FastAPI.
- Aucun appel direct à un SDK de LLM en dehors de `app/llm/`. Fournisseur et modèles uniquement via le `.env`.
- Les outils de l'agent (`app/tools/`) sont de simples fonctions, testables sans LLM.

## Structure

un readme en français pour github à la racine du projet

```
app/
  main.py          # create_app() : logs, CORS, routes ; objets partagés créés au démarrage (état de lifespan)
  config.py        # Settings (pydantic-settings) lus depuis .env
  logging_config.py
  api/             # routes FastAPI (health.py, candidates.py, rag.py, interviews.py, agent.py…) ; dependencies.py donne un accès typé à request.state
  llm/             # port LLM (base.py), adaptateurs (gemini.py), choix de l'adaptateur (factory.py)
  data/            # données du cahier des charges, contenu identique, noms traduits
  models/          # schémas Pydantic (candidate.py, cv_analysis.py, hr_assistant.py, agent.py…)
  services/        # logique métier, sans FastAPI (candidate_store.py, cv_reader.py, cv_parser.py,
                   #   structured_output.py, policy_index.py, hr_assistant.py, agent.py, agent_chat.py…)
  tools/           # outils de l'agent (interviews.py, candidates.py) et leur description pour le LLM (definitions.py)
frontend/          # interface HTML/CSS/JS sans build ni dépendance, servie à la racine par FastAPI
  index.html, styles.css, js/   # un module par page (cv, candidates, hr, chat) ; textContent uniquement (pas d'innerHTML)
scripts/
  check_llm.py     # appel réel au LLM : python -m scripts.check_llm
  evaluate.py      # mesure les critères d'évaluation (tableaux du README)
tests/             # pytest ; conftest.py fournit test_settings, fake_llm, policy_index et client (sans .env ni réseau)
  fakes.py         # FakeLLMClient (réponses prévues), FakeEmbeddingFunction et build_pdf
  real_llm.py      # run_with_real_llm : appel au vrai LLM dans les tests -m llm
  fixtures/cvs/    # CVs atypiques fictifs pour les tests de robustesse (-m llm), dont un CV piégé (injection)
  fixtures/rag_trap_questions.txt  # questions pièges du RAG, partagées par les tests et scripts/evaluate.py
```


## Règles à ne jamais enfreindre

IMPORTANT :
- **Ne jamais modifier le contenu des données fournies** par le cahier des charges : POLITIQUES_RH, OFFRE_POSTE_DEV_PYTHON, CANDIDAT_EXEMPLE_1/2, AGENDA_RECRUTEUR (les noms de variables sont traduits, voir « Comment travailler avec moi »).
- **Ne pas changer** le comportement, les docstrings ni les valeurs de retour de `search_interview_slots` et `book_interview` (seuls les noms sont traduits).
- Refus du RAG : la réponse doit dire que **la politique interne ne précise pas ce point**.
- Parsing : température 0.0, sortie validée par Pydantic, 2 appels maximum (1 appel + 1 relance si la réponse est invalide).
- Agent : toujours `search_interview_slots` avant `book_interview`.
- Clés API uniquement dans `.env`, jamais dans le code ni dans Git.
- Ne pas journaliser le contenu complet des CVs.

## Tests officiels (doivent toujours passer)

Détail dans `docs/cahier_des_charges.md`, section 8 :
1. Jean Dupont > 80 avec FastAPI/RAG ; Sophie Martin < 40
2. RTT + CET → réponse sourcée ; prime de naissance → refus
3. « Trouve-moi un créneau le 2026-10-15 … Jean Dupont » → recherche puis réservation

## Notes & décisions

<!-- Ajoute ici au fil du projet : choix faits, pièges rencontrés, choses à ne pas refaire. -->

- `RECRUITER_AGENDA` est modifié en mémoire par `book_interview` : tout test qui réserve un créneau doit remettre l'agenda à son état initial, sinon `tests/test_data.py` échoue selon l'ordre des tests.
- Dans les tests `-m llm`, passer par `run_with_real_llm` : un client Gemini ne survit pas à la fin de son `asyncio.run` (erreur « Event loop is closed »). Dans l'API, uvicorn n'a qu'une boucle, donc un seul client suffit.
- Le SDK Gemini bascule sur aiohttp dès qu'il est installé (ChromaDB l'installe) : `GeminiClient` lui impose un transport httpx, sinon les erreurs réseau échappent à `LLMError`.
- Quota Gemini gratuit : 15 requêtes/minute ; un 429 dans `pytest -m llm` n'est pas un bug, relancer le test une minute plus tard.
- Le refus RAG est rédigé par le code (`REFUSAL`), jamais par le LLM : il renvoie seulement `answered: false`. Une réponse sans source valide est aussi refusée.
