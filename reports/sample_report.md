mkdir -p data/raw
cat > data/raw/sample_financials.csv <<'EOF'
period,revenue,gross_profit,ebit,ebitda,net_income,current_assets,inventory,current_liabilities,total_assets,total_equity,total_debt,interest_expense
2023Q1,1000,400,150,200,90,500,120,350,2000,1000,700,30
2023Q2,1100,450,160,210,95,520,125,360,2050,1020,710,30
2023Q3,1200,480,170,220,105,540,130,365,2100,1040,720,30
2023Q4,1500,600,220,270,140,560,135,370,2200,1080,740,35
2024Q1,1400,560,210,260,130,550,140,380,2250,1100,750,35
EOF
