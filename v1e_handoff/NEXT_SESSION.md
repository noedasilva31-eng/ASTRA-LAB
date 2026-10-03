# Reprise exacte — V1e provenance

1. Extraire `ASTRA-V1e-provenance.zip` dans un dossier distinct. Conserver V1d,
   V1c et V1b validées sans modification.
2. Sur Windows, avec `SOLANA_RPC_URL` déjà configurée, exécuter uniquement :

   ```bat
   validate-provenance-windows.cmd
   ```

3. Exiger le nouveau rapport global PASS : 28 tests V1e, 31 V1d, 35 V1c,
   38 dépôt et 8 runner V1b ; 14 critères V1b ; contrôles réels de toutes les
   briques ; reconstruction hors réseau des données ET de leur provenance.
   Le rapport fourni dans cette archive est une exécution locale Linux : les
   contrôles réels y restent FAIL faute d'endpoint, sans requalification du
   PASS Windows V1d fourni séparément par l'utilisateur.
4. En cas de FAIL, utiliser les codes et métriques du rapport généré. Un slot
   non résolu ne devient pas skipped ; une erreur de décodage ne devient pas
   unsupported ; une absence de transfert supporté n'est pas un PASS réel.
   Les tests locaux et les archives de référence ne doivent pas être assouplis.
5. Après qualification Windows/Devnet V1e, geler cette version et ses rapports.
   Avant une brique suivante, reprendre le gate V1 de `docs/TESTING_ACCEPTANCE.md`.
   Restent notamment disponibilité physique/offsets, multi-provider, archive
   distante, quotas/alertes et soak 72 h. Aucune brique suivante n'est commencée ici.

Tous les compteurs et hashes sont vérifiés automatiquement. Les seules actions
externes requises pour qualifier cette livraison sont l'exécution Windows et
l'accès à l'endpoint déjà configuré. Ne pas communiquer sa valeur.

Ce fichier est le point de reprise V1e. Les NEXT_SESSION des versions antérieures
restent dans l'archive comme documents historiques intacts.
