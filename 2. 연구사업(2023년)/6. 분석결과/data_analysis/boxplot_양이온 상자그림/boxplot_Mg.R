# Load necessary libraries
library(ggplot2)
library(readxl)
library(ggrepel)
library(tidyverse)

setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/boxplot_양이온 상자그림")

# Load data
data <- read_excel('data_cation.xlsx')  # Replace 'your_data_file.xlsx' with your actual data file

# Subset for labeling (Adjust the condition based on your specific needs)
label_data <- subset(data, Mg >= 15)  # Replace 'your_threshold' with your specific threshold for Mg

# Calculating maximum values for each product or category
max_values <- data %>%
    group_by(Products) %>%
    summarise(max_Mg = max(Mg))

# Create a label for maximum values
max_values$label <- paste(max_values$max_Mg)

# Base plot
p <- ggplot(data, aes(x = Products , y = Mg, fill = Products)) +
    stat_boxplot(geom = "errorbar", width = 0.15) +
    geom_boxplot(outlier.shape = NA) +
    geom_point(data = subset(data, Mg > 15), aes(x = Products, y = Mg), color = "red", shape = 1) +
    # Add any additional lines or annotations specific to your data
    geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
    geom_text(data = max_values, aes(x = Products, y = max_Mg, label = label), vjust = -1.5, color = "blue")

p

# Rest of the plot customization (adjust according to your needs)
p + coord_cartesian(ylim = c(0, 70)) +
    scale_fill_manual(values =  c("Mineral-infused water" = '#36B7C3', "Bottled water" = '#3165AA')) +
    labs(x = "", y = "Mg(mg/L)") +
    theme_minimal() +
    theme(
        axis.title.x = element_text(size = 20, face = "bold"),
        axis.title.y = element_text(size = 20, face = "bold"),
        axis.text.x = element_text(size = 15, face = "bold"),
        axis.text.y = element_text(size = 15, face = "bold"),
        panel.background = element_rect(fill = "white"),
        legend.position = c(0.2, 0.9)
    )
