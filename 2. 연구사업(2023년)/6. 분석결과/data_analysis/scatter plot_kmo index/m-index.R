# 필요한 라이브러리 로드
library(ggplot2)
library(readxl)
setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/scatter plot_kmo index")

# 데이터 불러오기 (예: 'data.csv')
data <- read_xlsx('data.xlsx')

# 상자 그림 그리기
p <- ggplot(data, aes(x=factor(part, levels=c("Bottled water", "Mineral-infused water")), y=`M-index`)) +
    geom_boxplot(aes(fill=factor(part))) +
    stat_boxplot(geom = "errorbar", width = 0.25) +
    scale_fill_manual(values=c("lightblue", "lightgreen")) +
    theme_minimal() +
    theme(
        axis.title.x=element_blank(),
        axis.text.x=element_text(size=12),
        axis.title.y=element_text(size=14),
        axis.text.y=element_text(size=12)
    ) +
    labs(title="Box Plot of M-index by Part", y="M-index")
p
