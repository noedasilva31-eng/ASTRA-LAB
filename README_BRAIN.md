# ASTRA-V1-brain

Jalon additif : Brain explicable, suivi de thèse, sessions paper multi-opportunités,
dataset et freeze de recherche. Aucun ordre réel, aucune optimisation sur VSOF.
Lire BRAIN_ARCHITECTURE.md pour le support exact et les limites.

## Qualification Windows : une commande

```cmd
validate-all.cmd
```

Réutilise les variables existantes SOLANA_RPC_URL (Devnet),
ASTRA_OBSERVER_NETWORK=mainnet, ASTRA_OBSERVER_RPC_URL et ASTRA_OBSERVER_WS_URL
(Mainnet), et JUPITER_API_KEY si nécessaire. Ne pas inscrire leurs valeurs dans
les rapports ou le dépôt. websocket-client reste déclaré dans
requirements-observer.txt pour une installation neuve.

La gate conserve V1b/V1c/V1d/V1e/Observer/Bridge, les tests du jalon de mesure et
les nouveaux tests Brain. Le contrôle Brain utilise un dossier distinct
`all-validation-*/brain-proofs/` et dure au maximum 180 s de planification, avec
timeouts réseau bornés ; le worker global est limité à 270 s.

**Zéro trade n'est pas un échec du Brain** si des opportunités Mainnet ont été
réellement évaluées, archivées et rejouées. `real_brain_observations_audited`
qualifie cette instrumentation/décision, pas un round-trip ni une stratégie
rentable. Sans événement évalué : NOT_EXECUTED, aucune preuve fabriquée. Les
contrôles historiques restent indépendants et peuvent empêcher le PASS global.
La nouvelle gate remplace le contrôle live expérimental multi-cycle (non encore
qualifié) par cette qualification Brain ; les tests de son scheduler restent.

## Artefacts

- validation-summary.json/.txt : statut de tous les contrôles et causes.
- brain-proofs/brain-report.json : session, portefeuille, replay, freeze.
- brain-proofs/session-dataset.json : observations, scores, décisions et outcomes.
- brain-proofs/cycle-report.json/.txt : mesures paper et coûts.
- brain-proofs/raw.sqlite et state/*.sqlite : archives et matérialisations.
- brain-proofs/freezes/<hash>/ : SessionFreeze vérifiable hors réseau.
- V1E_PRESERVED_LAST.json : chemin/hashes des preuves V1e conservées.

## Reprise bornée explicite

```cmd
py -3 -m astra_brain --directory all-validation-XXXX/brain-proofs --seconds 180 --max-cycles 3
```

Même dossier = mêmes budgets, configuration, pertes et états ouverts. Aucun reset
ni clôture forcée. Un budget épuisé conserve les positions : ne pas prétendre les
avoir liquidées. Les snapshots/datasets déjà gelés restent distincts ; la reprise
produit un nouveau freeze de l'état étendu. Audit hors réseau : même commande avec
`--offline`. Pour une archive classique, utiliser astra_measure selon
README_MULTICYCLE.md, pas la commande Brain.

Les documents README_MULTICYCLE.md et COST_MODEL.md décrivent la première partie
du jalon et le modèle inchangé. Les paramètres courants du Brain et la commande
ci-dessus font foi pour cette livraison.
