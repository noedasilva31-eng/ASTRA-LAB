# ASTRA-V1-paper — progrès et limites exactes

Commande unique de validation : `validate-all.cmd`.

La référence externe ASTRA-V1-observatory reste inchangée. Le retour utilisateur
Windows/Helius Devnet est conservé dans paper_handoff/WINDOWS_USER_EVIDENCE.json :
255 tests PASS, gate/Local FAIL sur V1e live_provenance, V1d et Integrated visibles
PASS. Le code combiné V1e ne suffit pas à distinguer événement absent, plage
incomplète et erreur de décodage. Ce sprint ne le transforme pas en PASS, ne lance
pas des plages aléatoires et ne prétend pas avoir vérifié indépendamment ce retour.

## Mainnet et PumpSwap routé

Le client Mainnet READ ONLY et ses vérifications genesis restent en place, ainsi
que la séparation Devnet/Mainnet. Aucun signing, wallet, sendTransaction ou ordre
réel n'est ajouté. Les contrôles réels continuent d'utiliser ASTRA_OBSERVER_RPC_URL,
ASTRA_OBSERVER_NETWORK=mainnet et ASTRA_OBSERVER_WS_URL pour le streaming.
SOLANA_RPC_URL reste le endpoint Devnet historique.

Nouveau : le chemin transactionnel reconnaît les instructions PumpSwap internes
à un routeur lorsque leur profondeur et la sous-arborescence CPI sont prouvées.
Le décodeur de protocole existant vérifie toujours les comptes parent/événement,
le programme, l'autorité self-CPI et le schéma binaire. Un événement d'un frère
ne peut pas authentifier un autre appel ; une profondeur manquante reste unresolved.
L'identifiant inclut la position du parent interne et de l'événement émis. Le
chemin dataset astra_dex historique reste inchangé : ce support nouveau se trouve
dans astra_execution/routed.py et astra_observer/spine.py.

Les tests sont synthétiques. Aucun endpoint utilisateur n'est disponible dans
Work pour ce sprint ; aucune nouvelle capture réelle ni qualification Mainnet
n'est revendiquée. Les inconnus de schéma continuent de produire error/unsupported.
Launch/bonding/migration avant PumpSwap restent à implémenter.

## Mesures de transport préparées pour le vrai provider

Le streaming archive désormais la durée réception de notification → fin du
traitement, mesurée sur l'horloge monotone de la machine. Les durées aller-retour
HTTP déjà archivées sont agrégées en p95/p99. Les rapports distinguent ces durées
de la latence émission-provider → réception, qui reste NOT_MEASURED. Sans connexion
réelle, les chiffres des tests ne sont pas présentés comme une latence Helius.
L'hydratation HTTP reste séquentielle : ce n'est pas une qualification HFT.

## Quote evidence : format indicatif, pas preuve de fill

astra_execution/quotes.py lit une réponse ExactIn Jupiter v1 **déjà archivée**.
Il vérifie l'identité de chaîne préalable, les mints, la quantité demandée, le
seuil de sortie/slippage, le slot, les routes et l'intégrité de la frame. Il refuse
une cotation sans route, incohérente ou rattachée à une autre requête.

Il s'agit d'un contrat d'import/replay, pas d'un nouveau service de cotation live.
La documentation officielle signale que Swap v1 est remplacé par Swap V2 :
https://developers.jup.ag/docs/api-reference/swap/v1/quote
Aucun appel obsolète automatique ni credential nouveau n'est imposé à la gate.
Une route indicative ne prouve pas une exécution, une profondeur totale, l'état
des autorités, ni une possibilité de sortie certaine. Ces preuves réelles restent
à acquérir. Le prix quote n'est jamais promu en prix exécuté.

## Ledger PAPER conditionnel

Le nouveau module astra_execution/paper.py permet de tester le cycle :
intention BUY/REJECT → quote ultérieure → position conditionnelle → intention SELL
→ quote ultérieure → clôture → résultat de scénario. Il conserve les décisions,
états fournis, politique Risk, modèle, références de quotes et chaîne de hashes.
Les montants sont entiers bruts dans une seule monnaie de compte configurée.
La configuration, le code, le modèle et les limites sont figés dans le ledger.

Contraintes effectives :
- quote archivée disponible au moment de la décision, jamais future ;
- quote de règlement à un slot ultérieur (+1 par défaut, +3 configurable) ;
- TTL, quantité et sens exacts ; même preuve de quote que celle fournie au Risk ;
- nouveau passage Risk au règlement, kill switch inclus ;
- exposition/position/cash issus du ledger, non fournis par la stratégie ;
- un ordre en attente à la fois ; absence de position SELL refusée ;
- déduplication, rollback atomique, refus des conflits et de la corruption.

Les limites d'entrée libellées en monnaie de compte ne sont pas appliquées à tort
aux quantités de token d'une SELL qui ne fait que liquider une position entière.
Les autres vetos santé/quote/kill restent appliqués. Il n'y a pas de vente à découvert.

Le modèle prend le plus conservateur du seuil de quote et d'une décote configurable,
puis applique un coût fixe explicite en monnaie de compte. Les frais inclus dans la
quote ne sont pas ajoutés une seconde fois. Le coût fixe est une **hypothèse de
scénario** : il ne prétend pas mesurer base/priority fees, tips ou ATA. Les variations
de frais et le délai en slots sont configurables dans une nouvelle session, jamais
modifiés rétroactivement dans un ledger existant.

Tous les résultats portent CONDITIONAL_PAPER_SCENARIO / CONDITIONAL_PAPER_NOT_EXECUTED_TRADES.
Les tests BUY/SELL sont des fixtures synthétiques. Il n'existe **aucun fill réel ou
paper sur données réelles qualifié** dans cette livraison.

Frontière de confiance restante : les champs autorités/liquidité/santé d'OpportunityState
sont encore des entrées du moteur Risk, pas des attestations reconstruites par ce
nouveau module. Les fixtures positives les déclarent explicitement. Tant que les
collecteurs de ces preuves manquent, le flux observatory réel reste PARTIAL et
NO_TRADE. Le ledger conditionnel n'est pas branché à une entrée BUY automatique.
Ne pas exposer la construction d'états Risk à des stratégies/agents non fiables ;
un fournisseur de preuves validées constitue la prochaine dépendance obligatoire.
Le journal paper recalcule son historique : il est encore hors Hot Path.

Audit hors réseau d'un ledger (lecture seule, sortie nouvelle) :

```bat
python -m astra_execution --ledger SESSION\paper.sqlite --output AUDIT.json
```

Cet audit vérifie chaîne et comptabilité ; il ne certifie pas les autorités ou
l'exécutabilité de l'OpportunityState fourni. Le raw quote archive doit être conservé
avec le ledger pour auditer les références de cotation.

## Ce qui reste avant une boucle paper réelle

1. Qualification des captures Mainnet (y compris formats PumpSwap/CPI effectivement
   observés) et mesures Helius réelles ; diagnostic V1e Devnet conservé séparément.
2. Source de quotes actuelle, raw archivé et provenance ; états mint/authorities,
   liquidité, sorties et santé/couverture réellement prouvés.
3. Branchement données vérifiées → Risk → ledger paper ; modèle de coût/exécution
   calibré et stressé, sans assimiler une quote à une transaction réussie.
4. Launch/bonding/migration ; finalité/réconciliation des événements confirmés.
5. Connexion du PnL et des résultats de décisions à l'Outcome Tracker, qui continue
   pour l'instant de suivre indépendamment les marks de l'univers observé.

V1 entière n'est pas terminée. Aucun contrôle réel non exécuté n'est déclaré PASS.
