# ASTRA Brain V0.1 — Market Context Hydration

Version additive issue de ASTRA-V1-brain. Observer, Evidence, Risk, Bridge, ledger
et le package Brain V0 sont inchangés et protégés par PROTECTED_COMPONENTS.json.
Aucun seuil économique, frais ou support de devise n'a été élargi pour créer des trades.

## Windows : commande unique

```cmd
validate-all.cmd
```

Réutiliser les endpoints via l'environnement uniquement : SOLANA_RPC_URL doit
être **Devnet**, ASTRA_OBSERVER_RPC_URL et ASTRA_OBSERVER_WS_URL doivent être
**Mainnet**, ASTRA_OBSERVER_NETWORK=mainnet. JUPITER_API_KEY reste facultative selon
l'accès du fournisseur de quotes. Ne pas écrire les valeurs dans le dépôt.
websocket-client reste déclaré dans requirements-observer.txt.

La nouvelle phase utilise `all-validation-*/context-proofs/` : nouvelle session,
aucune modification du run Windows de référence. Les gates historiques restent
obligatoires. La session dure 180 s de planification avec worker limité à 270 s,
200 tentatives RPC/quotes cumulées et au plus 3 cycles. Le contrôle d'admission de
50 plans se fait entre transactions atomiques ; une transaction comprenant
plusieurs événements peut dépasser ce nombre (ce qui explique la limite de
planification, pas une garantie de exactement 50 observations).

## Hydratation courte et persistante

Un candidat Evidence-PROVEN, Risk admissible, flow non négatif et manquant seulement
d'historique peut déclencher un suivi ciblé du pool. Les données déjà archivées
sont utilisées immédiatement ; la collecte complémentaire cherche seulement des
transactions plus récentes que le slot initial, sans réécrire l'horodatage d'un
ancien événement. Le brut et les réponses/listings sont conservés avant traitement.

Une tentative par pool et par session : 20 s, 3 polls au maximum, au plus 6 nouvelles
transactions, deux essais au maximum par signature. Les compteurs sont persistants,
réservés avant I/O, et partagent le budget RPC existant. Expiration, clock regression,
veto Evidence/Risk, retournement défavorable ou budget atteint arrêtent l'hydratation.
Une expiration pendant l'acquisition Evidence interdit aussi l'intention BUY.
Un changement d'état paper passe au suivi ciblé qualifié existant. Fin de fenêtre :
aucune liquidation ni fill forcé. Zéro trade peut être un résultat d'observation valide.

Reprise d'une session V0.1, même dossier, mêmes budgets/pertes/positions :

```cmd
py -3 -m astra_context --directory all-validation-XXXX/context-proofs --seconds 180 --max-cycles 3
```

Audit/reconstruction sans réseau : ajouter `--offline`. Le code refuse de convertir
implicitement une session Brain V0 existante en V0.1. Les nouvelles configurations
sont immuables pendant une session. Le rapport read-only astra_measure reconnaît
les archives V0 et V0.1 ; les anciens snapshots sont rejoués avec le Brain V0 exact.

## Contrat du contexte et score

Fenêtre bornée à 60 s et 64 événements d'un pool, sur le temps de disponibilité.
Les champs distinguent KNOWN / DERIVED / UNKNOWN / STALE et gardent unités, sources,
slots, available_at, version et provenance. Les observations ne prétendent pas
couvrir tous les swaps de la chaîne. Un compteur zéro du sous-ensemble reçu est une
mesure valide ; une dimension non collectée reste null.

Conditions obligatoires pour un score numérique : au moins 3 swaps, durée observée
>= 2 s, aucun écart observé > 15 s, dernière observation <= 5 s, ordre des slots
cohérent, momentum/flow et preuves quote/réserves/impact suffisamment fraîches.
Sinon score=null avec la liste exacte `required_missing` / `missing_dimensions`.
Ces bornes sont des exigences explicites de contexte versionnées, pas un changement
silencieux des seuils Risk ou du notionnel.

Les poids historiques restent marché 50 %, exécution 30 %, qualité 20 %. Le marché
conserve momentum 60 % et flow 40 %. La décomposition détaille valeurs, contributions,
liquidité, exécution, Risk et confiance. Risk reste un veto indépendant (aucun bonus
ne le compense). La confiance probabiliste et des pénalités monétaires supplémentaires
restent UNKNOWN ; elles ne sont pas inventées pour remplir la décomposition.

## Mesures

Disponibles lorsque couvertes : prix successifs, rendements, momentum court (trois
derniers prix) et fenêtre moyenne, accélération, volatilité RMS des rendements
observés (non annualisée), drawdown, volume/flow/imbalance observés, vitesses et
accélération de l'activité, évolution des réserves entre preuves comptes, impact,
quote indicative à la taille demandée, fraîcheur/écarts/anomalies.
L'âge du pool reste connu seulement si une création prouvée est présente.

Regime V0.1 : INSUFFICIENT_DATA, QUIET, TRENDING_UP/DOWN, ACCELERATING/DECELERATING,
REVERSAL_RISK, HIGH_VOLATILITY, LIQUIDITY_STRESS, avec raisons et entrées archivées.
Un momentum court contradictoire avec la fenêtre moyenne interdit une candidature
BUY. La gestion de position conserve la logique conjointe du Brain V0 : une seule
baisse n'impose pas SELL, et un veto Risk ne peut jamais être contourné.

Toujours UNKNOWN/non garanti : profondeur réellement exécutable complète, future
liquidation, frais réellement payés par ASTRA, couverture totale, âge non prouvé,
confiance calibrée et MAE/MFE exécutables complets. Une réserve et une quote
indicative ne constituent pas une garantie de fill.

## Preuves et rapports

- context_handoff/reference-audit.json et REFERENCE_AUDIT.md : 51 décisions du run
  Windows reconstruites, quatre causes exactes des scores nuls, audit des devises.
- context_reference/all-validation-3qductr2/ : preuves Windows conservées, y compris
  leurs FAIL ; aucune assimilation à une qualification V0.1.
- context-proofs/context-report.json : état, compteurs, audit et freeze V0.1.
- context-proofs/session-dataset.json : contexte de chaque REJECT/NO_TRADE/decision,
  observations futures disponibles et journal d'hydratation.
- freezes/<hash>/ : dataset et SQLite liés par hashes, reconstruction hors réseau.
- validation-summary.json/.txt : gate complète, causes explicites.
- context_handoff/NEXT_SESSION.md : point de reprise courant. Les README.md et
  NEXT_SESSION.md racine restent des références historiques hashées.

L'analyse hors ligne peut proposer une calibration ; elle ne modifie aucun
paramètre pendant une session. Aucun ordre réel, aucun BUY/SELL synthétique pour
qualifier le live. La rentabilité et l'amélioration hors échantillon ne sont pas prouvées.
