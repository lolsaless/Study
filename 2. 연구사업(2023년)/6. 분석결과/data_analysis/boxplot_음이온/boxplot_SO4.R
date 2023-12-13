# Load necessary libraries
library(ggplot2)
library(readxl)
library(ggrepel)
library(tidyverse)

setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/boxplot_음이온")

# Load data
data <- read_excel('data_anion.xlsx')  # Replace 'your_data_file.xlsx' with your actual data file

# Subset for labeling (Adjust the condition based on your specific needs)
label_data <- subset(data, SO4 >= 15 & SO4 < 50)  # Replace 'your_threshold' with your specific threshold for SO4

# Calculating maximum values for each product or category
max_values <- data %>%
    group_by(Products) %>%
    summarise(max_SO4 = max(SO4))

# Create a label for maximum values
max_values$label <- paste(max_values$max_SO4)

# Base plot
p <- ggplot(data, aes(x = Products , y = SO4, fill = Products)) +
    stat_boxplot(geom = "errorbar", width = 0.15) +
    geom_boxplot(outlier.shape = NA) +
    geom_point(data = subset(data, SO4 > 15), aes(x = Products, y = SO4), color = "red", shape = 1) +
    # Add any additional lines or annotations specific to your data
    geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
    geom_text(data = max_values, aes(x = Products, y = max_SO4, label = label), vjust = -1.5, color = "blue") +
    geom_hline(yintercept = 250, color = "red", linetype = "dashed") +
    annotate("text", x = Inf, y = 250, label = "Standard 250 <", vjust = -0.5, hjust = 6.5, color = "red")

# Rest of the plot customization (adjust according to your needs)
p + coord_cartesian(ylim = c(0, 300)) +
    scale_fill_manual(values =  c("Mineral-infused water" = '#36B7C3', "Bottled water" = '#3165AA')) +
    labs(x = "", y = expression(atop(bold(SO[4]~"(mg/L)")))) +
    theme_minimal() +
    theme(
        axis.title.x = element_text(size = 20, face = "bold"),
        axis.title.y = element_text(size = 20, face = "bold"),
        axis.text.x = element_text(size = 15, face = "bold"),
        axis.text.y = element_text(size = 15, face = "bold"),
        panel.background = element_rect(fill = "white"),
        legend.position = c(0.2, 0.9)
    )

# Rest of the plot customization (adjust according to your needs)
p + coord_cartesian(ylim = c(0, 50)) +
    scale_fill_manual(values =  c("Mineral-infused water" = '#36B7C3', "Bottled water" = '#3165AA')) +
    labs(x = "", y = expression(atop(bold(SO[4]~"(mg/L)")))) +
    theme_minimal() +
    theme(
        axis.title.x = element_text(size = 20, face = "bold"),
        axis.title.y = element_text(size = 20, face = "bold"),
        axis.text.x = element_text(size = 15, face = "bold"),
        axis.text.y = element_text(size = 15, face = "bold"),
        panel.background = element_rect(fill = "white"),
        legend.position = c(0.2, 0.9)
    )

