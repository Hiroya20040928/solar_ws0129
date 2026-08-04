# live / live_wifi 低層実装資料

- PDF: `solarcar_live_low_level_reference.pdf`
- TeX: `solarcar_live_low_level_reference.tex`
- 対象ファイル: `live_file_inventory.csv`
- 関数・呼出し・属性読書き: `live_function_inventory.csv`
- ROSパラメータ・publisher・subscription・timer: `live_ros_interface_inventory.csv`
- 機械可読監査結果: `live_static_inventory.json`
- 全ページ目視監査: `qa/pdf_visual_audit.json`、`qa/contact_*.png`

再生成:

```powershell
python scripts/generate_live_low_level_reference.py --package-root . --output-dir docs/live_low_level_reference
Push-Location docs/live_low_level_reference
xelatex -interaction=nonstopmode -halt-on-error solarcar_live_low_level_reference.tex
xelatex -interaction=nonstopmode -halt-on-error solarcar_live_low_level_reference.tex
Pop-Location
python scripts/audit_pdf_visual.py docs/live_low_level_reference/solarcar_live_low_level_reference.pdf --output-dir docs/live_low_level_reference/qa
```
