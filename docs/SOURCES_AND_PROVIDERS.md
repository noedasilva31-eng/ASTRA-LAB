# Sources et évaluation d'infrastructure

Documentation officielle consultée le 29 septembre 2026. Aucune API commerciale n'a été appelée ; aucune couverture, tarification, rétention ou latence de compte n'est validée. Les URLs servent de références à revérifier lors de l'intégration. Pas de fournisseur engagé.

| Sujet | Vérification officielle | Implication ASTRA |
|---|---|---|
| Solana getBlock | https://solana.com/docs/rpc/http/getblock — paramètres d'encodage, commitment et version de transaction ; blockTime nullable | Conserver version, bloc brut et temps inconnu ; backfill ne remplace pas un historique de réception |
| Solana blockSubscribe | https://solana.com/docs/rpc/websocket/blocksubscribe — méthode indiquée instable et dépendante de flags du validateur | Ne pas supposer sa disponibilité sur tout RPC |
| Yellowstone / Triton | https://docs.triton.one/project-yellowstone/dragons-mouth-grpc-subscriptions — flux comptes, transactions et slots, protobuf versionné | Candidat streaming ; vérifier version client, couverture, replay, quotas et reconnexion sur le compte réel |
| Historique Triton | https://docs.triton.one/project-yellowstone/old-faithful-historical-archive — interfaces historiques RPC/gRPC | Candidat backfill ; vérifier bornes de rétention et disponibilité avant sélection |
| Helius parsing | https://www.helius.dev/docs/enhanced-transactions/overview — couche de transactions interprétées | Candidat enrichissement ; conserver RPC brut et mesurer couverture, jamais assimiler parsing et vérité complète |
| PostgreSQL | https://www.postgresql.org/docs/current/transaction-iso.html — isolation transactionnelle | Snapshot de lecture stable ; sérialisation des promotions avec retry complet |
| NATS JetStream | https://docs.nats.io/concepts/jetstream — persistance, replay, livraisons au moins une fois | Déduplication côté consommateur et ACK après commit restent nécessaires |
| S3 Object Lock | https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html — rétention WORM par version | Immutabilité de production exige configuration et permissions ; un hash seul ne suffit pas |
| X search | https://docs.x.com/x-api/posts/search/introduction — interface de recherche de posts | Évaluer droits, accès historique et quotas du compte avant V2 social ; aucun scraping ou accès supposé |

## Options retenues ou différées

RPC : interface standard Solana pour backfill et contrôle ; comparer Triton et Helius sur le même jeu de slots/signatures. Streaming Yellowstone candidat principal, JSON-RPC/WebSocket solution de couverture limitée et fallback selon capacités. Exiger matrice méthodes, finalité, programmes, rétention, failover, rate limits, qualité d'erreur et coût total. Le fallback ne garantit pas même latence ni même disponibilité : annoter chaque bascule.

Parsing DEX : décodeurs locaux versionnés par programme/version d'account pour la reproductibilité ; enrichissement fournisseur secondaire. Avant activation d'un protocole, obtenir sa documentation officielle, fixtures de transactions v0 et legacy, adresses de lookup tables, inner instructions, Token-2022 et cas d'échec. Ces décodeurs ne sont pas construits ici ; pas de liste d'adresses de programmes inventée.

Social : adaptateur X et éventuellement sources sous licence ; disponibilité réelle = réception, pas timestamp de publication seul. Budget et accès non connus. Distinguer post édité/supprimé et copie/republication. Mesurer les lacunes par source et langue.

Données/infra : PostgreSQL metadata, stockage objet brut ; Parquet/ClickHouse après benchmark de scans ; Redis et NATS différés jusqu'au besoin mesuré. OpenTelemetry/Prometheus comme candidats pour logs/traces/metrics ; version et intégration à vérifier avant installation. Secret manager du cloud choisi ultérieurement ; pas de fichier .env distribué contenant des secrets. Déploiement V1b envisagé sur VM supervisée avant orchestration plus lourde, avec volume durable, sauvegarde séparée et alertes.

## Benchmark d'achat à exécuter en V1b

Échantillon prospectif identique de programmes/slots ; conserver horloge monotone locale et UTC synchronisée. Comparer lag p50/p95/p99, taux de messages manquants, doublons, forks, précision decoding, durée/limites de replay et coût par volume. Injecter déconnexion de 1 minute puis 15 minutes ; vérifier trous résiduels et reprise. Comparer fournisseurs à leurs offres réellement accessibles, pas aux chiffres marketing. Documenter divergences et résultat nul. Aucune mesure de cette matrice n'a été exécutée faute d'accès réseau/provider dans ce workspace.
