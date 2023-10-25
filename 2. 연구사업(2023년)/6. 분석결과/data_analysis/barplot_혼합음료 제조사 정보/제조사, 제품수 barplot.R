library(ggplot2)
library(readxl)

# C:
setwd("C:/Git/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/혼합음료 제조사 정보")

# barplot
data <- read_xlsx("data_barplot.xlsx")

# Order data by '제조사' in descending order
data <- data[order(-data$Manufacturer), ]

# Create the bar plot using ggplot2
p <- ggplot(data, aes(x=reorder(region, -Manufacturer), y=Manufacturer, label=paste("n:", Product))) +  # Add "n:" to the label
    geom_bar(stat="identity", fill="#696969", alpha=0.5) +
    geom_text(aes(y=Manufacturer + 1), vjust=-0.5) +
    labs(title="", y="Manufacturer", x="region") +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))

print(p)

# barplot(제조사, 제품수 서로 변경)
data <- read_xlsx("data_barplot.xlsx")

# Order data by '제품수(Product)' in descending order
data <- data[order(-data$Product), ]

# Create the bar plot using ggplot2
p <- ggplot(data, aes(x=reorder(region, -Product), y=Product, label=paste("n:", Manufacturer))) +  # Swap 'Manufacturer' and 'Product'
    geom_bar(stat="identity", fill="#696969", alpha=0.8) +
    geom_text(aes(y=Product + 1), vjust=-0.5) +
    labs(title="", y="Product", x="region") +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))

print(p)

# bubble chart

# Data Loading from the Excel file
data <- read_xlsx("data_barplot.xlsx")

# Create the bubble chart using ggplot2
p <- ggplot(data, aes(x=region, y=Manufacturer, size=Product, label=paste("n:", Product))) + 
    geom_point(aes(color=Product), alpha=0.6) +  # Use geom_point for bubble chart
    geom_text(aes(y=Manufacturer + 1), vjust=-0.5) +
    labs(title="", y="Manufacturer", x="region", size="Product") +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1),
          legend.position="bottom")

print(p)

