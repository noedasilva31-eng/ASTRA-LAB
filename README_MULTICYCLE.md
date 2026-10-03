# ASTRA — jalon borné multi-opportunités

Version additive issue de ASTRA-V1-live-session. Observer, Evidence, Risk, Bridge,
ledger et critères V1e sont identiques à la référence : voir
PROTECTED_COMPONENTS.json (contrôlé automatiquement dans la gate).
Aucune transaction construite, signée ou envoyée. Les résultats paper restent des
scénarios conditionnels sur quotes indicatives, jamais des exécutions réelles.

## Commande Windows unique de qualification

Depuis ce dossier, avec les variables Helius déjà configurées :

```cmd
validate-all.cmd
```

SOLANA_RPC_URL reste l'endpoint Devnet historique. ASTRA_OBSERVER_RPC_URL et
ASTRA_OBSERVER_WS_URL sont exclusivement Mainnet, avec
ASTRA_OBSERVER_NETWORK=mainnet. JUPITER_API_KEY reste optionnelle selon l'accès au
fournisseur de quotes. Aucun endpoint/secret à écrire dans un fichier du projet.
Le package websocket-client de requirements-observer.txt reste nécessaire pour
le streaming (installation initiale : `py -3 -m pip install -r requirements-observer.txt`).
La gate ne fait aucune installation implicite.

La gate exécute toutes les non-régressions puis une session distincte de 120 s,
plafonnée à trois cycles complets et 200 tentatives RPC/quotes cumulées.
Les appels synchrones déjà commencés gardent leur timeout borné ; 120 s est la
fenêtre de planification, pas une interruption arbitraire d'un commit.
Le worker global est borné à 210 s.
Deux cycles conditionnels complets au minimum sont nécessaires au nouveau PASS
réel multi-opportunités. Ce seuil qualifie plusieurs cycles, pas une performance
financière. Zéro ou un cycle => NOT_EXECUTED / multiple_real_cycles_not_qualified,
avec état réel conservé. Aucun résultat historique ne remplace ce contrôle.
Tout FAIL/NOT_EXECUTED laisse la gate globale non PASS et son exit code non nul.
Les résultats locaux restent distingués dans validation-summary.json/.txt.

## Artefacts et reprise

`all-validation-*/multi-proofs/` conserve raw.sqlite, state/engine.sqlite,
state/paper.sqlite, session-report.json, cycle-report.json et cycle-report.txt.
Pas de TemporaryDirectory pour cette nouvelle session : les états ouverts
restent disponibles. Le rapport JSON inclut censure/couverture, décisions,
rejets, quotes, preuves comptes, réserves, coûts, latences et provenance.

Reprendre une session existante, sans remise à zéro du budget, des pertes, du
cash ou des positions :

```cmd
py -3 -m astra_multicycle --directory all-validation-XXXX/multi-proofs --seconds 120 --max-cycles 3
```

Le plafond de cycles et le budget sont immuables pour ce dossier. Un budget
épuisé ne peut pas être rechargé par relance. Une nouvelle qualification complète
crée un autre portefeuille de validation isolé, jamais une reprise implicite.
Un seul writer par dossier. Pas de liquidation forcée en fin de fenêtre.
NO_TRADE, PENDING_BUY, OPEN_POSITION et PENDING_SELL restent explicites.
REJECT et NO_TRADE portent une couverture OBSERVED_SUBSET : ils ne décrivent pas
les opportunités non observées et ne suffisent pas à mesurer les faux négatifs.

Rapport hors réseau, à partir d'archives arrêtées ou copiées de manière cohérente :

```cmd
py -3 -m astra_measure --session all-validation-XXXX/multi-proofs --output rapport-cycle
```

Le lecteur ne se connecte jamais aux SQLite originales : il copie main/WAL dans
un répertoire temporaire, puis vérifie/rejoue les copies. Il ne répare pas une
archive corrompue et ne modifie pas les données sources. Ne pas lancer un lecteur
séparé pendant qu'un writer externe modifie les bases ; la session intégrée
produit son rapport sous son verrou exclusif. Les bases archivées réelles VSOF
sont livrées comme fixture de reconstruction, pas comme substitut au live.

## V1e : conservation, critères inchangés

Le wrapper v1e_preserve.py copie les octets des phases avant nettoyage vers
`provenance_validation/preserved-astra-provenance-validation-*/`.
V1E_PRESERVED_LAST.json indique le chemin et les hashes. Il faut conserver ce
répertoire entier : blocks.sqlite, journal.sqlite, dataset.json, rebuilt.json,
rapports de phases et éventuels WAL/SHM/journaux associés. Les rapports de gate
restent dans provenance_validation/provenance-report-* et all-validation-*.
Un échec de copie fait échouer le wrapper et préserve le répertoire temporaire
original plutôt que de supprimer l'unique preuve.

L'ancien cas des 137 transactions n'est pas rediagnostiqué sans ses blocs bruts.
Le diagnostic établi reste : couverture source complète, events=0,
decoder_errors=0. Cela ne démontre ni un défaut du décodeur ni un décodage réussi.
Le critère continue à refuser events=0. La prochaine capture conservée permettra
l'examen exact de chaque transaction, y compris les instructions non supportées.

## Mesures et registre des coûts

Voir COST_MODEL.md et multicycle_handoff/vsof/cycle-report.json.
Aucune modification économique : deux forfaits de 2 100 000 lamports,
soit 0,0042 SOL par round-trip, restent inchangés. UNKNOWN n'est jamais zéro.
Les frais réellement payés par d'autres transactions observées ne sont pas
attribués à une transaction ASTRA qui n'a pas eu lieu.
