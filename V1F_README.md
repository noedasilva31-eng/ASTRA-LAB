# ASTRA V1f — correctif Windows, validation racine, quotas locaux

Nouvelle version construite depuis le ZIP V1e. Les dossiers et ZIP V1b/V1c/V1d/V1e
précédents restent intacts. Dans cette copie, le seul fichier V1e modifié est
`provenance_validation/run.py` : lectures UTF-8 explicites et localisation sûre
des exceptions. Les modules métier et les 98 fichiers de référence V1d restent
inchangés. Les empreintes décodeur/normaliseur/provenance sont conservées.

## Commande unique Windows

```bat
validate-all.cmd
```

Python 3.12+ ; `SOLANA_RPC_URL` déjà défini pour les contrôles réels.
Lanceur non interactif, ordre V1b → V1c → V1d → V1e → nouveaux tests locaux.
Sous Windows, le lanceur V1b original est appelé sans modification ; les autres
validateurs sont exécutés une fois chacun. Aucun secret n'est demandé, affiché
ou placé dans les rapports. Les sorties brutes des sous-processus ne sont pas
journalisées. Toutes les bases de test sont temporaires et dédiées.

À la racine : `validation-summary.json` et `validation-summary.txt`, remplacés
par les résultats de la nouvelle exécution. Chaque exécution conserve aussi un
dossier `all-validation-*` avec rapports détaillés JSON et résumé texte.
Chaque FAIL affiche directement couche, contrôle, code et cause. Les exceptions
V1e indiquent aussi type, fichier, fonction et ligne sans recopier les arguments
ou corps RPC. Aucun `findstr` nécessaire. Le résumé conserve le nombre de tests
exécutés et réussis par suite.

Timeouts maximaux par gate : V1b 450 s (runner Linux 90 s séparé), V1c 600 s,
V1d 780 s, V1e 900 s, nouveaux tests 180 s. Les workers internes gardent leurs
propres délais bornés. Les autres gates continuent après un FAIL pour fournir
un bilan complet. Le code de sortie est non nul si un contrôle échoue ou un
rapport est absent/incohérent. Sans endpoint, les contrôles réels sont FAIL,
`local_overall` distingue les tests locaux réussis du verdict global incomplet.
`--self-test` désactive volontairement le réel sans le déclarer PASS.
Linux : `python3 -B validate_all_current.py`.

## Incompatibilité Windows corrigée

Le rapport Windows V1e joint contient un seul FAIL : `live_provenance`,
`phase_exception`, `UnicodeDecodeError`. Le JSON et le texte concordent.
Dans ce worker, `Journal.export` écrit le dataset en UTF-8 avec les caractères
Unicode préservés. Après reconstruction et comparaison binaire, `pipeline`
lisait le dataset avec `export.read_text()` sans encodage. Sous un Python
Windows utilisant CP1252 par défaut, certains octets UTF-8 ne sont pas décodables.
Les fixtures ASCII précédentes ne révélaient pas ce problème.

Toutes les lectures texte de ce runner indiquent désormais `encoding='utf-8'`.
Aucun `ignore` ou `replace` n'est utilisé. Le test de régression injecte des logs
Unicode dans un bloc, simule CP1252 pour les lectures sans encodage et exécute
la chaîne capture → publication → reprise → export → reconstruction. Il prouve
que l'ancienne lecture CP1252 échoue sur ce même fichier tandis que la chaîne
corrigée passe et conserve exactement les octets. Un autre test rejette un JSON
contenant de l'UTF-8 invalide, sans produire de reconstruction.

Le rapport reçu ne contenait pas la pile ni le dataset réel. Le chemin fautif
est identifié dans le code et reproduit localement ; le nouveau passage réel
sur Windows reste nécessaire. La correction ne modifie ni brut, ni document,
ni hash, ni classification de slot, ni preuve de provenance.

## Brique indépendante : réservations de quotas locales

`astra_budget/` ajoute une primitive SQLite séparée, testable sans RPC :

- Politique immuable : nombre maximal de demandes et plafond d'unités entières.
  Les unités sont abstraites, pas une estimation implicite du prix Helius.
- Réservation durable avant autorisation. Vérification et insertion dans une
  transaction `BEGIN IMMEDIATE`, partagée par les connexions concurrentes.
- Même identifiant : aucune seconde autorisation d'envoi. Contenu divergent :
  conflit. Après crash, une réservation non réglée reste entièrement imputée.
- Règlement idempotent d'un montant connu inférieur ou égal à la réservation.
  Une consommation supérieure n'est pas acceptée silencieusement. Le nombre
  de demandes ne diminue jamais ; seul le surplus d'unités peut être libéré.
- Journal append-only, contrôle de hashes, snapshot et reconstruction dans un
  nouveau fichier fermé avant publication. La reconstruction restaure l'état
  du budget, sans autoriser ni effectuer de nouvelle demande réseau.

API : `Budget(path, requests=..., units=...)`, `reserve(id, estimated_units)`,
`settle(id, actual_units)`, `audit()`, `snapshot()`, `rebuild(snapshot, new_path)`.
L'identifiant doit être un identifiant interne non secret, jamais une URL/API key.
`authorized=False` sur un doublon signifie **ne pas renvoyer la demande**.
Une réponse perdue exige une réconciliation externe ; pas de remboursement
inconditionnel au redémarrage.

Cette primitive n'est **pas branchée aux collecteurs RPC**. Elle ne prouve donc
pas encore la limitation effective d'un fournisseur ni la maîtrise de ses coûts.
Elle ne dépend pas de la qualification Windows du correctif Unicode. Elle est
validée localement uniquement ; intégration RPC, alertes et politique de
réconciliation restent des travaux ultérieurs.

Voir `v1f_handoff/NEXT_SESSION.md`, `CHECKLIST.json` et les rapports courants.
Les autres README/NEXT_SESSION et rapports conservés sont historiques.
