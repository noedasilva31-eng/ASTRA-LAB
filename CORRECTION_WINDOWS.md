# Correctif ciblé : fermeture de la connexion SQLite de sauvegarde

La seule modification du code produit est dans `astra/store.py`, méthode
`Store.backup()`. Le context manager d’une connexion SQLite termine la
transaction mais ne ferme pas la connexion. La fermeture dépendait donc du
ramasse-miettes, et Windows pouvait encore verrouiller `backup.sqlite` au
moment de `TemporaryDirectory.cleanup()`.

Le correctif conserve le contexte transactionnel et ajoute `target.close()`
dans un `finally`. La connexion cible est fermée au retour normal et lorsqu’une
exception survient. Aucun `ignore_cleanup_errors`, retry de suppression,
`gc.collect()`, changement de schéma ou modification de `health()`.

Les 38 tests du dépôt sont inchangés. Deux tests de régression ont été ajoutés
à la suite du runner (8 tests au total). Ils conservent une référence forte à
la connexion cible et vérifient qu’elle est fermée, après succès et après
exception. Ils échouent tous deux avec le code original et passent avec le
correctif. Les connexions utilisées par le runner sont déjà fermées dans ses
blocs `finally` ; aucune autre correction de connexion n’a été nécessaire.

## Exécution Windows en une commande

Extraire ce package dans un **nouveau dossier**, avec Python 3.12+ et la variable
`SOLANA_RPC_URL` déjà définie pour l’endpoint Devnet. Depuis ce dossier :

```powershell
.\validate-windows.cmd
```

Cette commande exécute les 8 tests du runner, puis le validator intégral, qui
inclut les 38 tests du dépôt. Les rapports JSON/texte sont générés dans un
nouveau dossier `validator/v1b-report-*`. Les résultats de la suite du runner
s’affichent dans le terminal. Code final 0 uniquement si les deux suites passent.

Les scénarios restent isolés dans des bases temporaires : l’archive ne contient
aucun fichier `var/` ni aucune base de référence et le runner n’en ouvre aucune.
Le manifeste a été recalculé pour cette livraison. Aucun secret ajouté.

## Validation de cette livraison

Vérification effectuée sous Linux, pas sous Windows :

- 38/38 tests du dépôt PASS ;
- 8/8 tests du runner PASS ;
- 12/12 critères locaux du validator PASS ;
- 2 critères RPC réels non exécutés ici, faute d’endpoint configuré.

Le rapport synthétique conserve ces deux critères en FAIL explicite. Il ne
constitue pas une preuve Windows ou live. **Résultat attendu sur Windows :
38/38 dépôt + 8/8 runner + 14/14 critères validator PASS**, avec l’endpoint fourni.
Aucune lecture manuelle des compteurs ni coupure Internet n’est requise.
