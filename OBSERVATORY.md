# ASTRA — observatoire incrémental

## Point de départ et validation

La référence externe ASTRA-V1-operations reste intacte. Le résultat utilisateur
Windows/Helius Devnet communiqué après le ZIP est reconnu : ASTRA PASS, Local PASS,
225 tests PASS. Cette déclaration est distincte des vérifications exécutées ici.
Les anciennes briques ne sont pas réimplémentées. La gate unique reste :

```bat
validate-all.cmd
```

Les tests déterministes nouveaux sont découverts par la même gate. Les nouveaux
contrôles réels ont un statut NOT_EXECUTED lorsque leurs prérequis manquent ; le
verdict global reste non-PASS et le code de sortie reste non-zéro. Un manque de
configuration Mainnet n'est pas un défaut local du code ni une invalidation du
PASS Devnet antérieur.

## Mainnet lecture seule, séparé du socle Devnet

`astra_observer` utilise ses propres archives SQLite et vérifie le genesis du
réseau explicitement choisi. Le réseau devient immuable pour chaque archive.
Le client n'autorise que getGenesisHash, getSignaturesForAddress et getTransaction.
Il ne possède aucune méthode d'envoi de transaction ni wallet. Le budget persistant
est réservé avant chaque tentative HTTP, en O(1), sans remboursement en cas de panne.
Le transport existant filtre les échos de secrets et les erreurs ne journalisent
jamais l'URL. Les timeouts HTTP sont bornés, les recherches et subscriptions aussi.

Configuration dans l'environnement (sans mettre les valeurs secrètes en fichiers) :
- SOLANA_RPC_URL : endpoint Devnet historique, inchangé.
- ASTRA_OBSERVER_NETWORK : `mainnet` pour la qualification représentative.
- ASTRA_OBSERVER_RPC_URL : endpoint HTTP du réseau choisi.
- ASTRA_OBSERVER_WS_URL : endpoint WSS correspondant pour le contrôle streaming.

La gate exige les variables explicites ASTRA_OBSERVER_* pour les nouveaux contrôles
Mainnet. Elle n'envoie pas silencieusement des requêtes Mainnet sur l'endpoint Devnet.
Les commandes manuelles acceptent également Devnet avec `--network devnet`.

```bat
python -m astra_observer search --network mainnet --directory observer-run --seconds 60
python -m astra_observer stream --network mainnet --directory observer-stream --seconds 30
```

Le streaming nécessite la dépendance optionnelle `requirements-observer.txt`.
Le cœur, les tests simulés, la recherche HTTP et le replay utilisent la stdlib.
Un nouvel environnement peut installer ce fichier avec pip ; le validateur ne
modifie pas automatiquement les dépendances du poste.

## Event spine et périmètre temps réel

Adaptateur WSS logsSubscribe confirmé → archivage notification → getTransaction
confirmé → archivage réponse brute → adaptateur PumpSwap existant → moteur unique.
Un replay des mêmes réponses archivées utilise exactement le même moteur.
Le flux est indépendant des exports JSON, de Timeline.verify, des historiques
reconstruits et de tout LLM. Les snapshots/export et audits complets sont hors
traitement par événement. Les fenêtres de features sont bornées (64 événements
par défaut). Le reçu, l'état et la décision sont engagés atomiquement en SQLite.

**Ce n'est pas encore un feed transactionnel Yellowstone ni un Hot Path de
production qualifié.** La notification ne contient pas toutes les données :
l'hydratation HTTP séquentielle ajoute de la latence et limite le débit. Il n'y a
pas encore de file concurrente/backpressure qualifiée, reconnect automatique ou
réconciliation finale. Toute session/reconnexion est PARTIAL ; aucune couverture
complète n'est annoncée. Les transactions confirmées ne sont pas assimilées à une
finalité définitive. getBlock finalized reste disponible dans le socle historique
pour backfill/réconciliation ; ce sprint ne le présente pas comme du streaming.

Sources de contrat :
https://solana.com/docs/rpc/websocket/logssubscribe
https://solana.com/docs/rpc/http/gettransaction
https://solana.com/docs/references/clusters

## PumpSwap, launch et CPI

Le décodeur courant est réutilisé sans changer son schéma validé synthétiquement.
Le nouveau chemin transactionnel relie signature/slot/réseau/événement/pool/wallet/
mints/montants au brut et à la preuve genesis. Les signatures de réponse doivent
correspondre à la requête. Les instructions top-level avec self-CPI direct prouvé
sont prises en charge ; les swaps routés restent explicitement unsupported.
Les réponses null restent unresolved. L'historique d'erreurs reste archivé et le
replay peut poursuivre vers une réponse ultérieure réussie.

La recherche réelle est bornée et exige au moins un événement décodé. Une recherche
vide échoue. Les preuves de la gate sont conservées sous all-validation-*/observer-proofs.
L'essai local sur RPC public Mainnet a échoué à la connexion : aucune capture
PumpSwap réelle n'a été obtenue. Aucun support Mainnet protocolaire n'est qualifié
par ce résultat. Launch/bonding/migration Pump avant AMM restent à implémenter ;
une création de pool observée ne prouve pas une migration ou le lancement du token.

## Universe Census et OpportunityState

Chaque pool décodé est recensé avant toute sélection de stratégie. Les pools sans
trade restent dans l'univers observé. Le census est un sous-ensemble couvert par
le feed, jamais l'univers Solana complet. Premier instant observé ≠ instant de
création. Les opportunités de décisions conservent réseau, pool, mints, venue,
slot/event_time, availability_ns, version, fenêtre d'événements et provenance.

Features incrémentales : ratio quote/base brut observé, variation sur fenêtre,
montants quote cumulés, évolution entre demi-fenêtres, compteurs buy/sell, wallets
uniques sur fenêtre et première apparition observée d'un wallet par pool. Les
ratios sont rationnels exacts ; les décimales des tokens ne sont pas devinées.
Le ratio inclut la sémantique des montants wallet rapportés (achat/sortie), ce n'est
ni un spot universel ni un prix exécutable. La variation de demi-fenêtre n'est pas
nommée accélération par seconde : celle-ci reste NOT_COLLECTED. Les réserves ne
sont pas arbitrairement transformées en liquidité exécutable.

Données non collectées explicites : autorité, holders, bundles, cotation de sortie,
liquidité exécutable, social. Une absence n'est pas un zéro. Les fenêtres suivent
l'ordre de disponibilité ; les événements tardifs sont signalés. Les décisions
antérieures sont immuables et n'acquièrent jamais les observations futures.
L'horloge est locale ; une régression de disponibilité est refusée, sans prétendre
que sa synchronisation externe ou sa disponibilité physique est qualifiée.

## Outcome Tracker indépendant des trades

Pour chaque pool ayant un swap observé, un ancrage est créé avant tout filtre
stratégique. Horizons par défaut : 1 min, 5 min, 30 min, 1 h, 24 h. Le premier mark
observé à/après l'horizon fournit un rendement de mark et un drawdown observé,
avec retard exact, événement d'ancrage, événement de résultat et couverture PARTIAL.
Les outcomes concernent donc aussi tous les refus NO_TRADE.

Si aucune observation n'arrive, le résultat reste NOT_COLLECTED. Un mark tardif ne
prétend pas être le prix à l'horizon exact. Prix liquidable et survie restent
inconnus : ni absence de flux = pool mort, ni mark théorique = sortie possible.
Le module suit un premier ancrage par pool ; l'échantillonnage de nouveaux ancrages
et les outcomes relatifs à chaque décision sont des extensions restantes.

## Risk et statut PAPER exact

Risk est une fonction déterministe : taille/exposition/nombre de positions,
liquidité/slippage, perte de session, quote TTL/taille/sortie, données anciennes
ou incomplètes, heartbeat, autorités et kill switch. La policy de l'Engine est
immuable ; un changement exige une autre instance. Les tests positifs de Risk
utilisent des preuves de cotation **synthétiques**, pas une preuve réelle.

Le moteur émet actuellement une décision auditable **NO_TRADE** et le statut
BLOCKED_MISSING_EXECUTION_EVIDENCE. Il n'a pas de fournisseur de cotation ou
d'autorités suffisamment prouvé pour autoriser une position. Il n'existe donc
pas encore de fills, de portefeuille paper financé, de modèle d'impact/frais
complet, de sortie ni de PnL paper réalisé. Le champ compte de Risk est nul dans
cette stratégie d'observation sans positions ; il ne représente pas un compte
trading actif. Ne pas présenter cette livraison comme une boucle de trading
paper complète. Cette limite est volontairement visible plutôt qu'un fill parfait
inventé. Aucun ordre réel n'est possible dans ce client.

## Replay, reprise et mesures

```bat
python -m astra_observer replay --network mainnet --source observer-run\raw.sqlite --directory observer-rebuild
```

Les publications sont idempotentes, les identités conflictuelles refusées. Au
redémarrage, le replay traite les frames archivées avant l'interruption. Les audits
complets d'archives et la comparaison de reconstruction sont hors chemin critique.
Les checksums détectent une corruption ; ils ne sont pas une attestation cryptographique
indépendante du fournisseur ou une protection contre un administrateur malveillant.

Le benchmark livré mesure 300 événements synthétiques locaux, avec p95/p99 par
étage. Il n'inclut pas la latence fournisseur ni une mesure Windows. Les mesures
sont dans observatory_handoff/benchmark.json. Le stockage WAL/FULL conserve la
durabilité ; ses coûts réels doivent être mesurés sur le poste cible.

Les recherches réelles, la qualification streaming, le routage CPI, le launch,
les quotes/authorities, le paper complet et la qualification longue restent à faire.
