# Upstream Pod Template Definitions (for Tapis Pods Templates API)

Use these template payloads to register reusable Pods templates for the Upstream bundle. The values are based on the existing Admin UI blueprints, with placeholders for per-environment secrets and base names.

## Template IDs
- `upstreampostgrestemplate`
- `upstreamapitemplate`
- `upstreamuitemplate`

## How to register
1) Copy the matching `*-template.json` file.
2) Replace placeholder tokens (`{{BASE}}`, `{{PG_USER}}`, `{{PG_PASSWORD}}`, `{{CKAN_ADMIN_API_KEY}}`) with your real values before posting **but never commit secrets**. Leave `CKAN_ADMIN_USERNAME` as `dso_test` unless you use a different CKAN admin user.
3) POST to Pods Templates:  
   ```bash
   curl -X POST "$PODS_BASE_URL/v3/pods/templates" \
     -H "X-Tapis-Token: $TAPIS_TOKEN" \
     -H "Content-Type: application/json" \
     --data-binary @upstream-docker-pods/templates/upstream-postgres-template.json
  ```
4) Repeat for the API and UI templates.

## Notes
- The template payload goes in the `template` field expected by the Pods Templates API. The `pod_id` values include placeholders so you can instantiate with different bases per lab/system.
- The API template includes `CKAN_ADMIN_API_KEY`, `CKAN_ADMIN_USERNAME`, and `CKAN_ORGANIZATION` so the backend can add users to the `upstream` CKAN org without exposing the key to the UI. Do not commit real secrets to source control—inject them when registering the template or via overrides.
