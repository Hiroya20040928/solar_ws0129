# solar_package_flow_workbook

改良版ソーラーカーパッケージの処理フローを、ワークシート形式で説明する資料です。

## Source

- `solar_package_flow_workbook.tex`

## Rebuild

```powershell
cd docs\flow_workbook
xelatex -interaction=nonstopmode solar_package_flow_workbook.tex
xelatex -interaction=nonstopmode solar_package_flow_workbook.tex
```

## Notes

- 2026-07-16 時点のワークツリーと install 側スクリプトを根拠にしています。
- `measure / live / live_wifi` の launch 本体は現ワークツリー直下に見当たらないため、資料内では「入口設計」と「確認できた core 実装」を分けて説明しています。
