# Deployment and operation manual

- `solar_mpc_deployment_operation_manual.md`: searchable source manual.
- `solar_mpc_deployment_operation_manual.tex`: XeLaTeX source.
- `solar_mpc_deployment_operation_manual.pdf`: print-ready manual.

Regenerate and build with:

```powershell
pandoc solar_mpc_deployment_operation_manual.md --standalone --toc `
  --number-sections --shift-heading-level-by=-1 --pdf-engine=xelatex `
  --variable CJKmainfont="Yu Gothic" --variable CJKmonofont="Yu Gothic" `
  --variable papersize=a4 --variable geometry:margin=18mm `
  --output solar_mpc_deployment_operation_manual.tex
xelatex -interaction=nonstopmode solar_mpc_deployment_operation_manual.tex
xelatex -interaction=nonstopmode solar_mpc_deployment_operation_manual.tex
```

The checked PDF is distributed with the fitted solar-only package and the
blank vehicle package.
