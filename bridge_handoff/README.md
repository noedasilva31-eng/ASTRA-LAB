# Pont Mainnet vers scénarios paper

Le nouveau module `astra_bridge` raccorde le streaming existant au ledger paper
existant. Aucune transaction n'est construite, signée ou envoyée. Aucun wallet
n'est demandé. Ce n'est ni une stratégie validée ni une preuve de rentabilité.

## Exécution

Une fois les dépendances installées, `validate-all.cmd` lance les suites locales
et les contrôles réseau configurés. Les secrets viennent uniquement de
l'environnement : `SOLANA_RPC_URL` reste Devnet ; `ASTRA_OBSERVER_NETWORK=mainnet`,
`ASTRA_OBSERVER_RPC_URL` et `ASTRA_OBSERVER_WS_URL` désignent Mainnet. Ne pas
intervertir les deux réseaux. `JUPITER_API_KEY` est facultative côté client ;
si le fournisseur exige une clé ou refuse l'accès, le refus est conservé.
Aucune valeur d'environnement n'est inscrite dans les rapports.

Session bornée, dans un **nouveau dossier dédié** :

```
py -3 -B -m astra_bridge stream --directory sessions\mainnet-paper-001 --seconds 60
```

Relancer sur le même dossier reprend les plans préparés sans renouveler leurs
preuves ni leur date de décision. Budget persistant : 200 tentatives partagées
entre hydratation, quotes et comptes ; son épuisement bloque les nouveaux appels.
Un verrou de session empêche deux processus CLI d'écrire simultanément.

Audit hors réseau :

```
py -3 -B -m astra_bridge audit --directory sessions\mainnet-paper-001
```

`kill` et `unkill` remplacent `audit` pour archiver un changement de kill switch
entre deux exécutions. Le kill switch interdit également les fills en attente.
Une interruption avant préparation devient un REJECT explicite à la reprise,
et jamais une entrée rétroactive. Les intentions sans règlement restent pending ;
aucune liquidation n'est inventée pour vider le portefeuille.

## Preuves et vetos

Chaque swap décodé entre d'abord dans le census et l'Outcome Tracker existants,
y compris si toute décision paper est ensuite refusée. Le pont :

1. Lie l'événement au brut, à la signature et au décodeur versionné.
2. Demande une cotation ExactIn directe, à la taille envisagée, dans le pool observé.
3. Demande la cotation inverse de la quantité obtenue selon le modèle paper.
4. Archive `getMultipleAccounts` : deux mints, deux vaults, pool. Vérifie les
   adresses issues de l'instruction, propriétaires, mint/freeze authority absentes,
   vaults initialisés non délégués, réserves et programme du pool.
5. Refuse les preuves futures, périmées, trop éloignées en slots, l'impact excessif,
   les routes indirectes/autres pools, les sorties dépassant les réserves observées.
6. Archive le plan, puis appelle le Risk et le ledger. Un règlement exige une
   nouvelle preuve dans un slot ultérieur, une date postérieure et un nouveau Risk.

Support : quote WSOL, mints SPL classiques sans extensions, et profil Token-2022
strict décrit dans bridge_handoff/OBSERVED_TOKEN_DIAGNOSIS.md. Toute autre extension,
autorité présente, route non directe ou élément inconnu : REJECT. Le contrôle
d'autorités **ne signifie pas qu'un token est sûr** : holders, bundles, deployer,
MEV, social et rug-risk complet ne sont pas qualifiés.

Les réponses sont archivées avant interprétation. Une erreur reste dans
l'historique même si une tentative ultérieure réussit. Les exceptions exportées
sont des codes contrôlés, jamais le texte arbitraire d'une réponse HTTP.

## Modèle paper explicite

Candidate mécanique de qualification : BUY de 0,01 SOL sur un swap observé,
règlement sur un événement ultérieur compatible, puis demande SELL de toute
la position au prochain swap observé. Pas de signal d'alpha ni promotion LIVE.

Capital fictif : 1 SOL. Position maximale (frais inclus) : 0,02 SOL ; exposition
0,04 SOL ; réserve quote minimale : 1 SOL ; perte/session maximale : 0,01 SOL.
La politique et le modèle sont figés dans les empreintes de session.

Frais réseau/ATA/priorité : **budget supposé** de 0,0021 SOL par jambe, non mesuré.
Les frais DEX sont inclus dans la quote du fournisseur. Sortie retenue : minimum
entre le seuil de la quote et un haircut de 25 bps. Impact maximal : 100 bps.
TTL quote/comptes/événement : 5 secondes. Écart inter-preuves : au plus 16 slots ;
une quote ne peut dépasser l'événement de plus de 150 slots. Aucun délai observé
n'est remplacé par une valeur imaginaire. L'acquisition est synchrone et bornée ;
elle peut dépasser le TTL et provoquer un REJECT. Ce pont n'est pas un moteur HFT.

La profondeur est ici une réserve observée + une cotation à taille donnée,
pas une courbe de carnet. La cotation inverse établit une route indicative à T,
pas une garantie qu'une vente sera exécutable ensuite. Les positions et PnL sont
**CONDITIONAL_PAPER_SCENARIO**, jamais présentés comme des transactions exécutées.

`coverage=OBSERVED` dans l'état Risk a le périmètre explicite
`decision_local_accounts_and_two_direct_quotes`. La couverture du flux et du
marché demeure PARTIAL / OBSERVED_SUBSET ; aucun trou n'est déclaré comblé.

## Provenance, reconstruction et mesures

`raw.sqlite` contient événements, réponses de cotation, comptes, plans et résultats
avec chaînes de hashes. Le plan relie les références brutes, l'événement, les
features immuables à T, le Risk, les identifiants d'intention/règlement et la position.
Le ledger reconstruit cash, inventaire et PnL réalisé. Le rapport contient aussi
les outcomes observés pour les pools rejetés ; leur prix reste un mark, non un prix
liquidable. Les outcomes non encore observés restent NOT_COLLECTED.

L'audit reconstruit les décisions et le portefeuille dans des bases temporaires
sans accès réseau, puis compare les résultats. Les latences locales d'acquisition,
HTTP et réception-notification→traitement sont mesurées ; la latence d'émission du
fournisseur reste NOT_MEASURED. Des quotes peuvent expirer pendant leur acquisition.

## Qualification encore nécessaire

L'adaptateur GET-only utilise le contrat de compatibilité Jupiter
`https://api.jup.ag/swap/v1/quote`, documenté sur
`https://developers.jup.ag/docs/api-reference/swap/v1/quote`.
La v1 n'est plus activement maintenue ; cet adaptateur reste **NON QUALIFIÉ RÉELLEMENT**
dans Work. Il ne requiert pas de taker et n'appelle aucun endpoint de transaction.
L'accès sans clé est espacé de 2,05 s ; 401/403/429 restent des échecs explicites.
Les APIs v2 pouvant impliquer un taker ne sont pas substituées silencieusement.

La gate distingue l'acquisition réelle d'une preuve de décision de l'aller-retour
paper réel conditionnel. Un REJECT conforme ne vaut pas preuve d'un BUY/SELL réussi.
L'absence de credentials est NOT_EXECUTED, et la gate globale n'annonce pas PASS.
Les PASS Windows/Mainnet de 280 tests appartiennent à ASTRA-V1-paper uniquement.
