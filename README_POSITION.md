# ASTRA Position Brain V0.2 — reprise ciblée paper

Cette version reprend la position du run Windows `all-validation-jyqge_an`.
La référence Windows complète reste dans `position_reference/`, inchangée.
Aucun nouveau BUY, aucune découverte, aucun ordre réel dans cette nouvelle session.
Les modules Observer, Evidence, Risk, Bridge, ledger, Brain V0 et Context V0.1
restent identiques. Voir PROTECTED_COMPONENTS.json et position_handoff/CHANGES.json.

## Point de reprise courant

Lire **position_handoff/NEXT_SESSION.md**. Le NEXT_SESSION.md racine est une
ancienne référence hashée et ne doit pas être interprété comme le plan actuel.

Aucune validation Windows supplémentaire n'est nécessaire pour lire les rapports
livrés. Quand vous déciderez de poursuivre l'observation Mainnet de la position :

```cmd
resume-position-windows.cmd
```

Cette commande seule crée/reprend `position-continuation/` à partir des trois
SQLite archivés, vérifie le replay, puis suit uniquement le pool détenu.
Elle utilise ASTRA_OBSERVER_NETWORK=mainnet et ASTRA_OBSERVER_RPC_URL déjà fournis
par l'environnement. JUPITER_API_KEY reste facultative selon l'accès au fournisseur.
Ni valeur de credential ni URL complète dans les rapports. Le WSS n'est pas requis
pour ce suivi ciblé HTTP; websocket-client reste la dépendance Observer inchangée.

La reprise hors réseau est également possible :

```cmd
py -3 -B -m astra_position --source position_reference\all-validation-jyqge_an\context-proofs --directory position-continuation
```

Le mode hors réseau n'avance pas l'horloge du marché, n'acquiert aucune quote,
ne fabrique pas de nouvelle observation et ne clôture rien.

## État repris, conservation et budget

- Token : GqemxZqeMM9M9z9jA5b4Unpa6HUkhssPpeKW3egpump.
- Quantité : 4 624 230 **unités brutes**, sans supposer les décimales.
- Coût : 12 100 000 lamports paper = 0,0121 SOL, dont 2 100 000 simulés.
- Cash : 987 900 000 lamports paper = 0,9879 SOL.
- Ledger : une intention BUY et son règlement conditionnel, aucune SELL.

La copie est préparée dans un répertoire temporaire, vérifiée, puis renommée
atomiquement. Aucun original Windows n'est ouvert en écriture. Le manifeste lie
les SHA-256 sources, la tête d'archive, le ledger, l'entrée et la thèse historique.
La reprise répétée ne réinitialise ni capital, ni pertes, ni positions, ni budget.

Le précédent budget **188/200** reste dans `position_parent_rpc_budget` et dans
l'activation hashée. Le nouveau sprint reçoit explicitement une allocation
**distincte de 80 requêtes HTTP/quotes**, journalisée avant toute observation.
Ce n'est pas une réécriture des 188 appels précédents. La même continuation ne
renouvelle jamais ces 80 appels, même après crash ou nouveau processus.

Fenêtre persistante de 120 s à compter du premier lancement live, 16 polls maximum,
8 signatures par poll, au plus une nouvelle transaction par poll, 2 tentatives
maximum par signature. Réservation du poll et des appels avant I/O. Les transactions
échouées/anciennes/déjà traitées sont comptées; les observations existantes sont
réutilisées pour le contexte. Une acquisition en cours peut dépasser la fenêtre
jusqu'aux timeouts bornés des requêtes; aucune intention/règlement n'est appliqué
si son plan termine après l'échéance. Pas de réhorodatage d'événement ancien.

Une fenêtre terminée reste terminée au redémarrage. Une future allocation
supplémentaire nécessiterait une nouvelle étape explicite, non un reset silencieux.

## Thèse et décisions

La thèse au BUY existe déjà dans le snapshot Brain d'entrée. L'activation V0.2
la lie explicitement sans prétendre qu'un nouveau modèle tournait à cette date.
Chaque nouvelle observation liée à la position archive PositionHealth, sa thèse,
les données manquantes, les raisons HOLD/EXIT_CANDIDATE/VETO, Evidence et Risk.

Les seuils descriptifs existants restent : momentum <= -200 bps avec flow négatif,
réserves quote en baisse de 20 %, impact >= 100 bps. La nouvelle règle exige au
moins deux de ces trois facteurs sur **deux observations distinctes successives**,
fraîches et séparées de 15 s au maximum. Un trou, une dimension manquante ou une
preuve refusée ne produit pas de candidature. Une baisse isolée ne suffit pas.
Ces règles sont des hypothèses versionnées, non une stratégie validée rentable.

Thèse : INTACT / STRENGTHENING / WEAKENING / INVALIDATED / UNKNOWN.
Le veto Risk est prioritaire. EXIT_CANDIDATE passe encore par les fonctions
qualifiées Evidence/Risk/ledger avant une intention SELL; il n'est jamais un fill.
Le règlement nécessite une quote postérieure à la décision, un slot ultérieur et
une nouvelle validation Evidence/Risk. Un refus laisse l'état ouvert ou pending.
Une intention SELL acceptée peut rester PENDING_SELL jusqu'à une preuve valide.

V0.2 n'applique pas le déclencheur automatique TIME_BASED_EXIT du Brain V0.
La durée est mesurée; la fin d'une fenêtre n'est pas une raison de liquidation.
Les snapshots Context historiques/V0 restent intacts pour comparaison : **la
PositionHealth V0.2**, et non leur ancien champ exit, pilote les nouveaux plans.
Aucun paramètre économique, frais, taille ou limite Risk n'est modifié.

## Mesures et limites

Mesures quand disponibles : prix relatif à l'entrée paper (hors frais fixes),
momentum court/moyen, accélération, flow, activité/volume, volatilité, drawdown,
réserves et variation, impact de sortie et variation entre observations,
fraîcheur/continuité, durée, quote indicative à la taille exacte, PnL indicatif.

MAE/MFE sont calculés sur **les swaps réellement reçus depuis l'entrée**,
avec événements et provenances; ils ne sont pas des extrema exécutables ou une
couverture complète du marché. Profondeur réellement exécutable, causalité précise
des frais/impact, exécution future et outcome non observé restent UNKNOWN.

Après clôture, `position-review.json` fournit le cycle, prix/timestamps, PnL
brut/net selon le ledger existant, registre des coûts, raisons HOLD/SELL,
trajectoire PositionHealth et limites. Les frais forfaitaires restent SIMULATED.
Les données Mainnet/provider sont PROVEN, les calculs sont DERIVED, les scénarios
paper restent conditionnels. Aucune transaction ASTRA n'est envoyée.

## Rapports et non-régression

- position_handoff/reference-audit.json : replay et freeze réels archivés, position
  exacte, analyse V0.2 rétrospective clairement séparée des décisions Windows.
- position_handoff/offline-resume/ : copie reprise et rapport sans réseau.
- position-continuation/position-report.json : état, métriques réseau et replay.
- position-continuation/position-review.json : revue autonome et hash du dataset.
- validation-summary.json : gate locale et contrôles réseau manquants.

`validate-all.cmd` reste la gate d'intégration complète. Les 406 tests antérieurs
restent exécutés et les tests Position s'y ajoutent. La nouvelle phase live remplace
la découverte Context par une copie de la position de référence, sans nouveau BUY.
Pour ce sprint, seule la gate **locale --self-test** est exécutée dans Work.
Les anciennes validations réelles ne sont pas revendiquées comme réexécutées.

Le contrôle live V0.2 exige une **nouvelle PositionHealth** durant l'invocation.
La seule position historique n'est jamais une preuve de nouvelle qualification.
Sans observation nouvelle : NOT_EXECUTED (`no_new_position_observation`). Une erreur
source pendant le suivi est conservée en FAIL (`position_source_error`), pas
reclassée en absence de prérequis. Un HOLD nouvellement observé peut qualifier le
suivi; il ne qualifie pas une sortie. Le quota atteint reste une borne normale.
Le compteur `observations_reused` compte les signatures déjà traitées rencontrées
lors des polls; les réutilisations de contexte sont traçables séparément par les
listes `coverage.window_events` de chaque PositionHealth. Aucun compteur ne
prétend couvrir l'ensemble des swaps Mainnet.
