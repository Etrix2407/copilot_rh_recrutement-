# Scénario de démo (5 minutes)

Objectif : rejouer les 3 tests officiels du cahier des charges dans l'interface, sans passer par `/docs`.

## Avant la démo

1. Si la démo a lieu après le 14/10/2026, mettez `DEMO_DATE=2026-10-14` dans le `.env` **avant** de lancer le serveur : l'agenda du cahier des charges ne contient que les 15 et 16/10/2026, et l'agent doit les considérer comme à venir. Le `.env` n'est lu qu'au démarrage : après toute modification, redémarrez le serveur.
2. Lancez (ou relancez) le serveur, **sans** `--reload` pour éviter un redémarrage en pleine démo :
   `uvicorn app.main:create_app --factory --no-proxy-headers`.
   L'agenda du recruteur revient à son état initial : le créneau de 09:00 est libre.
3. Vérifiez que le LLM répond : `python -m scripts.check_llm`.
4. Ouvrez <http://localhost:8000/> et, dans l'onglet **Candidats**, supprimez les candidats des essais précédents.
5. Évitez de lancer `pytest -m llm` juste avant : la clé gratuite de Gemini limite le nombre de requêtes par minute (et par jour).

## Déroulé

### 0:00 – 0:30 · Présentation

> « Copilot RH aide un recruteur sur quatre tâches : analyser un CV, répondre aux questions RH, planifier un entretien, le tout dans un chat qui s'affiche en direct. »

Montrez les 4 onglets.

### 0:30 – 1:45 · Test officiel 1 : analyse de CV

1. Onglet **Analyser un CV**, bouton d'exemple **Jean Dupont**, puis **Analyser ce CV**.
2. Attendu : score **supérieur à 80** (jauge verte, « Très bon profil »), compétences **FastAPI** et **RAG** dans les étiquettes, justifications et points de vigilance.
3. Recommencez avec **Sophie Martin** : score **inférieur à 40** (jauge rouge).

> « Le JSON produit par le LLM est validé par un schéma Pydantic ; s'il est invalide, une seule relance est faite. »

### 1:45 – 2:15 · Tableau des candidats

1. Onglet **Candidats** : Jean Dupont et Sophie Martin apparaissent, statut **CV analysé**.
2. La ligne de synthèse résume le nombre de candidats par statut et le score moyen. Triez par score.
3. Cliquez sur le nom de Jean Dupont : son analyse complète s'ouvre sous le tableau.

> « Les candidats sont enregistrés en base : ils restent après un redémarrage, et le bouton Supprimer applique le droit à l'effacement. »

### 2:15 – 3:15 · Test officiel 2 : assistant RH

1. Onglet **Questions RH**, exemple **Jours de RTT et CET** : réponse avec **10 jours de RTT** et **5 RTT sur le CET**, encadré **Sources** (Politique de Congés & RTT).
2. Exemple **Prime de naissance** : réponse **« La politique interne ne précise pas ce point. »**, sans source.

> « La phrase de refus est écrite par le code, pas par le LLM : il ne peut pas inventer une règle. 12 questions pièges sont refusées dans les tests. »

### 3:15 – 4:30 · Test officiel 3 : agent de planification

1. Onglet **Planifier un entretien**, bouton **Exemple : entretien de Jean Dupont**, puis **Envoyer**.
2. Attendu, au fil de l'eau :
   - carte **🔧 Recherche de créneaux…** qui devient **✔ Recherche de créneaux**, avec le détail « 4 créneaux trouvés » ;
   - carte **✔ Réservation de l'entretien** (confirmation et invitation) ;
   - réponse affichée mot à mot.
3. Retour dans **Candidats** : Jean Dupont est passé à **Entretien planifié**.

> « L'agent cherche toujours avant de réserver : c'est garanti par le code, même si on lui demande d'ignorer ses règles. »

### 4:30 – 5:00 · Conclusion

> « Les 3 tests officiels passent aussi en automatique (`pytest -m llm`), avec un rapport de résultats dans le README : 9 CVs sur 9 analysés, 12 refus sur 12, et des audits offensifs dont les constats ont été corrigés ou documentés comme limites (docs/rapport_audit.md). »

## En cas de problème

| Symptôme | Cause probable | Que faire |
| --- | --- | --- |
| Le serveur s'arrête au démarrage avec « Configuration incomplète : … » | Variable absente ou invalide dans le `.env` | Compléter les variables citées (modèle : `.env.example`), puis relancer |
| Le premier démarrage est long | Téléchargement du modèle d'embedding (environ 80 Mo) | Attendre ; les démarrages suivants sont rapides |
| L'agent dit qu'aucun créneau n'est disponible ou que la date est passée | `DEMO_DATE` absente, ou ajoutée sans redémarrer | Mettre `DEMO_DATE=2026-10-14` dans le `.env`, puis redémarrer le serveur |
| « Le service d'IA est momentanément indisponible » | Quota Gemini par minute atteint | Attendre une minute, puis réessayer |
| « Trop de demandes en peu de temps » | Limite de 10 appels par minute de l'application | Attendre le délai indiqué |
| « Entretien non réservé : le dossier … est au statut « entretien planifié » » | Jean Dupont déjà planifié lors d'une répétition | Supprimer le candidat dans **Candidats**, puis refaire l'analyse |
| L'agent réserve 11:00 au lieu de 09:00 | 09:00 déjà réservé lors d'un essai | Normal (créneau suivant) ; redémarrer le serveur pour remettre l'agenda à zéro |
