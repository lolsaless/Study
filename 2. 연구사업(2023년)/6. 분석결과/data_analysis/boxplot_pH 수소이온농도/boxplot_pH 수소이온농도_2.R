library(ggplot2)
library(readxl)
library(ggrepel)

setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/boxplot_pH 수소이온농도")

data <- read_excel('data_pH.xlsx')

label_data <- subset(data, pH >= 9.5)

ggplot(data, aes(x = Products, y = pH, fill = Products)) +
    stat_boxplot(geom = "errorbar", width = 0.25) +
    geom_boxplot(outlier.shape = NA) +  # Hide default outliers
    geom_point(data = subset(data, pH > 9.5), aes(x = Products, y = pH), color = "red", shape = 1) + # Red circles for pH > 9.5
    geom_hline(yintercept = 4.5, color = "red", linetype = "dashed") +
    geom_hline(yintercept = 9.5, color = "red", linetype = "dashed") +
    annotate("text", x = Inf, y = 9.5, label = "Standard 9.5 <", vjust = -0.5, hjust = 6.5, color = "red") +
    annotate("text", x = Inf, y = 4.5, label = "Standard 4.5 >", vjust = -0.5, hjust = 6.5, color = "red") +
    geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
    coord_cartesian(ylim = c(4, 10)) +
    scale_fill_manual(values = c("Mineral-infused water" = '#FFD700', "Bottled water" = '#4682B4')) +
    labs(title = "",
         x = "",
         y = "pH") +
    theme_minimal() +
    theme(
        axis.title.x = element_text(size = 20, face = "bold"), # Adjust x-axis title size
        axis.title.y = element_text(size = 20, face = "bold"), # Adjust y-axis title size
        axis.text.x = element_text(size = 15, face = "bold"), # Adjust x-axis text size
        axis.text.y = element_text(size = 15, face = "bold"), # Adjust y-axis text size
        panel.background = element_rect(fill = "white"), # Set panel background to white
        legend.position = c(0.8,0.2)
    )
