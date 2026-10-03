# Reprise exacte — ASTRA V1f

Réalisé : correctif explicite UTF-8 de V1e, reproduction CP1252 pertinente,
UTF-8 invalide refusé ; `validate-all.cmd` non interactif ; résumé des contrôles,
codes et causes ; tests de robustesse du résumé ; module isolé de réservations
de quotas locales avec crash/reprise, idempotence, intégrité et reconstruction.
Aucune connexion entre ce module de quotas et le collecteur n'est encore faite.

Première action : extraire le ZIP dans un nouveau dossier sur Windows, avec
`SOLANA_RPC_URL` déjà configurée, puis exécuter :

```bat
validate-all.cmd
```

Le résultat et les causes d'échec sont imprimés et enregistrés à la racine dans
`validation-summary.json`/`.txt`. Les rapports détaillés sont dans
`all-validation-*`. Exiger PASS global avant de qualifier cette version
Windows/Devnet. Un PASS local Linux ne remplace pas cette exécution.

En cas de nouvel échec V1e, le résumé doit donner le contrôle, le code, le type
et la localisation. Conserver le rapport sans endpoint ni clé. Ne pas réduire
les invariants pour contourner un encodage ou une absence de données.

Après qualification Windows : geler cette version et ses preuves. Le travail
local suivant possible est l'intégration explicite des réservations avant
transport RPC, avec tests de dépassement et réponse perdue, puis alertes.
Définir les unités/quota fournisseur avant de prétendre contrôler ses coûts.
Ne pas transformer une réservation déjà vue en autorisation de réémettre.
La qualification Windows du correctif peut avancer séparément ; aucune nouvelle
couche ne doit être annoncée validée Windows sans PASS réel du lanceur racine.

Restent au gate V1 complet : intégration des quotas et alertes, réconciliation
multi-provider, disponibilité physique/offsets, archive distante/restauration,
backpressure et soak 72 h. V1 complet n'est pas déclaré validé.

Les baselines antérieures restent intactes. Le NEXT_SESSION courant est ce
fichier ; les versions conservées aux autres chemins sont historiques.
