library(ggplot2)
library(readxl)
library(ggrepel)
library(tidyverse)
# Set working directory
setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/boxplot_pH 수소이온농도")

# Load data
data <- read_excel('data_pH.xlsx')

# Subset for labeling
label_data <- subset(data, pH >= 9.5)

# Calculating maximum values for each product
max_values <- data %>%
    group_by(Products) %>%
    summarise(max_pH = max(pH))

# Create a label for maximum values
max_values$label <- paste(max_values$max_pH)


# Base plot
p <- ggplot(data, aes(x = Products, y = pH, fill = Products)) +
    stat_boxplot(geom = "errorbar", width = 0.25) +
    geom_boxplot(outlier.shape = NA) +
    geom_point(data = subset(data, pH > 9.5), aes(x = Products, y = pH), color = "red", shape = 1) +
    geom_hline(yintercept = 4.5, color = "red", linetype = "dashed") +
    geom_hline(yintercept = 9.5, color = "red", linetype = "dashed") +
    annotate("text", x = Inf, y = 9.5, label = "Standard 9.5 <", vjust = -0.5, hjust = 6.5, color = "red") +
    annotate("text", x = Inf, y = 4.5, label = "Standard 4.5 >", vjust = -0.5, hjust = 6.5, color = "red") +
    annotate("text", x = Inf, y = 7.89, label = "Standard 4.5 >", vjust = -0.5, hjust = 6.5, color = "red") +
    geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
    geom_text(data = max_values, aes(x = Products, y = max_pH, label = label), vjust = -1.5, color = "blue")

# Adding error bar annotations
p <- p + geom_text(data = error_bars, aes(x = Products, y = lower, label = paste("Lower:", round(lower, 2))), vjust = 2, hjust = 0.5) +
    geom_text(data = error_bars, aes(x = Products, y = upper, label = paste("Upper:", round(upper, 2))), vjust = -0.5, hjust = 0.5)

# Rest of the plot customization
p + coord_cartesian(ylim = c(4, 10)) +
    scale_fill_manual(values = c("Mineral-infused water" = '#FFD700', "Bottled water" = '#4682B4')) +
    labs(title = "", x = "", y = "pH") +
    theme_minimal() +
    theme(
        axis.title.x = element_text(size = 20, face = "bold"),
        axis.title.y = element_text(size = 20, face = "bold"),
        axis.text.x = element_text(size = 15, face = "bold"),
        axis.text.y = element_text(size = 15, face = "bold"),
        panel.background = element_rect(fill = "white"),
        legend.position = c(0.8,0.2)
    )
