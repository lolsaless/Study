
# R Code for Data Transformation and Plotting

## Importing Libraries
library(readxl)
library(ggplot2)
library(car)

## Reading Data
df <- read_excel("ca_data.xlsx")

## Data Transformation
# Transforming Ca
df$Transformed_Ca <- df$Ca - df$Ca_max

# Log Transformation
df$Log_Ca_max <- log(df$Ca_max + 1)
df$Log_Ca <- log(df$Ca + 1)

# Log Transformed Ca
df$Transformed_Log_Ca <- df$Log_Ca - df$Log_Ca_max

## Plotting
# Histogram
ggplot(df, aes(x=Transformed_Ca)) +
  geom_histogram(aes(y=..density..), bins=20, alpha=.5) +
  geom_density() +
  ggtitle("Histogram of Transformed_Ca")

# QQ-Plot
qqPlot(df$Transformed_Ca, main="QQ-Plot of Transformed_Ca")                                                                                                                                                                                 

# R Code for Plotting "Transformed Log Ca values by part"

# R Code for Plotting "Transformed Log Ca values by part"

## Importing Libraries
library(readxl)
library(ggplot2)
library(dplyr)

## Reading Data
df <- read_excel("ca_data_transformed.xlsx")

## Adding row numbers
df <- df %>% mutate(row_num = row_number())

## Plotting
ggplot(df, aes(x=row_num, y=Transformed_Log_Ca, color=part)) +
  geom_point() +
  geom_hline(yintercept=0, linetype="dashed", color = "red") +
  labs(title="Transformed Log Ca Values by Part", x="Index", y="Transformed_Log_Ca") +
  theme_minimal()

