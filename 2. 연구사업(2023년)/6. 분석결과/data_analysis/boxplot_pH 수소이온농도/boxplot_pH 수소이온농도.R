# Load necessary libraries
library(ggplot2)
library(readxl)
library(ggrepel)

setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/boxplot_pH 수소이온농도")

# Read the data from an Excel file
# Replace 'path_to_file.xlsx' with the actual path of your file
data <- read_excel('data_pH.xlsx')

# Filter the data to include only rows where pH >= 9.5
label_data <- subset(data, pH >= 9.5)

ggplot(data, aes(x = part, y = pH, fill = part)) +
    stat_boxplot(geom = "errorbar", width = 0.25) +
    geom_boxplot(outlier.shape = 1) + 
    geom_hline(yintercept = 4.5, color = "red", linetype = "dashed") + 
    geom_hline(yintercept = 9.5, color = "red", linetype = "dashed") +
    annotate("text", x = Inf, y = 9.5, label = "Standard 9.5 <", vjust = -0.5, hjust = 6, color = "red") + # Label for 9.5
    annotate("text", x = Inf, y = 4.5, label = "Standard 4.5 >", vjust = -0.5, hjust = 6, color = "red") + # Label for 4.5
    geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
    coord_cartesian(ylim = c(4, 11)) +
    scale_fill_manual(values = c("M" = '#FFD700', "B" = '#4682B4'))
    labs(title = "",
         x = "Group",
         y = "pH") +
    theme_minimal()