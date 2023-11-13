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

# Creating the boxplot with red lines and labels for pH >= 9.5
ggplot(data, aes(x = part, y = pH)) +
  geom_boxplot(outlier.shape = 1) + # Outliers circled
  geom_hline(yintercept = 4.5, color = "red", linetype = "dashed") + # Red line at y = 4.5
  geom_hline(yintercept = 9.5, color = "red", linetype = "dashed") + # Red line at y = 9.5
  geom_text_repel(data = label_data, aes(label = name_new), nudge_x = 0.25, nudge_y = 0.25) +
  coord_cartesian(ylim = c(2, 12)) + # Set y-axis limits
  labs(title = "Boxplot of pH Values for Groups M and B",
       x = "Group",
       y = "pH") +
  theme_minimal() # Minimal theme for a cleaner look
